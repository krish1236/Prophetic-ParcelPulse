"""End-to-end classification pipeline: event → Tier 0 → Tier 1 → (Tier 2) → alerts.

For each Tier-0 candidate we run Tier 1 (Haiku materiality screen). If
material AND `materiality_score >= TIER2_MATERIALITY_THRESHOLD`, we also
run Tier 2 (Sonnet decision trace). The trace replaces the placeholder
JSON in `alerts.decision_trace` and the alert's `classifier_tier` flips
to `'sonnet'`.

Two-layer dedupe is enforced:
  * event-layer: (source, external_id, payload_hash) UNIQUE on `events`
  * alert-layer: (watchlist_id, dedupe_key) UNIQUE on `alerts`

A daily LLM spend cap (`settings.daily_llm_cost_cap_usd`) gates BOTH tiers.
Once today's spend hits the cap, the worker stops calling Haiku/Sonnet and
remaining candidates stay in the events log for later runs. If Tier 2 fails
(API error, validation, hallucinated URL), we still write the alert with the
Tier 1 placeholder trace so the user sees the signal.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

import anthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import SessionLocal
from parcelpulse.materiality.tier0 import find_candidates
from parcelpulse.materiality.tier1 import MaterialityScreen, screen
from parcelpulse.materiality.tier2 import DecisionTrace, generate_trace
from parcelpulse.settings import settings

log = logging.getLogger(__name__)

# Tier 2 (Sonnet) only fires above this Tier 1 score. Below, we keep the cheap
# Haiku-only alert with a placeholder decision_trace.
TIER2_MATERIALITY_THRESHOLD = 60

_PLACEHOLDER_TRACE = '{"placeholder": true, "tier": "haiku"}'


def alert_dedupe_key(source: str, external_id: str, parcel_id: UUID) -> str:
    """Same source-event on the same parcel → same dedupe key (one alert per pair)."""
    return f"{source}:{external_id}:{parcel_id}"


_INSERT_ALERT_SQL = text("""
    INSERT INTO alerts (
        watchlist_id, parcel_id, triggering_event_id, axis,
        materiality_score, confidence, summary, decision_trace,
        classifier_tier, dedupe_key
    )
    VALUES (
        :wl, :pid, :eid, :axis, :score, :conf, :summary,
        CAST(:trace AS jsonb), :tier, :dedupe
    )
    ON CONFLICT (watchlist_id, dedupe_key) DO NOTHING
    RETURNING alert_id
""")


async def daily_cost_so_far(session: AsyncSession, day: date | None = None) -> float:
    """Sum classifier_cache.cost_usd inserted today (UTC)."""
    day = day or datetime.now(UTC).date()
    return float(
        (
            await session.execute(
                text(
                    "SELECT coalesce(sum(cost_usd), 0)::float "
                    "FROM classifier_cache "
                    "WHERE created_at >= :day "
                    "  AND created_at < :day + interval '1 day'"
                ),
                {"day": day},
            )
        ).scalar_one()
    )


async def _maybe_run_tier2(
    *,
    cand_event_id: UUID,
    cand_parcel_id: UUID,
    cand_watchlist_id: UUID,
    session: AsyncSession,
    screened: MaterialityScreen,
    client: anthropic.AsyncAnthropic | None,
) -> DecisionTrace | None:
    """Run Tier 2 if score is high enough AND budget remains. Returns trace or None."""
    if screened.materiality_score < TIER2_MATERIALITY_THRESHOLD:
        return None
    cost = await daily_cost_so_far(session)
    if cost >= settings.daily_llm_cost_cap_usd:
        log.warning(
            "daily LLM cost cap reached before tier 2 (%.4f >= %.2f); "
            "writing alert with placeholder trace",
            cost,
            settings.daily_llm_cost_cap_usd,
        )
        return None
    return await generate_trace(
        event_id=cand_event_id,
        parcel_id=cand_parcel_id,
        watchlist_id=cand_watchlist_id,
        session=session,
        tier1_screen=screened,
        client=client,
    )


async def classify_event(
    event_id: UUID,
    session: AsyncSession,
    *,
    anthropic_client: anthropic.AsyncAnthropic | None = None,
) -> int:
    """Run Tier 0 → Tier 1 → (Tier 2) for one event; write alerts. Returns count inserted."""
    candidates = await find_candidates(event_id, session)
    if not candidates:
        return 0

    event_meta = (
        await session.execute(
            text("SELECT source, external_id FROM events WHERE event_id = :e"),
            {"e": str(event_id)},
        )
    ).mappings().first()
    if event_meta is None:
        return 0

    written = 0
    for cand in candidates:
        cost = await daily_cost_so_far(session)
        if cost >= settings.daily_llm_cost_cap_usd:
            log.warning(
                "daily LLM cost cap hit (%.4f >= %.2f); skipping remaining candidates",
                cost,
                settings.daily_llm_cost_cap_usd,
            )
            break

        screened = await screen(
            event_id=cand.event_id,
            parcel_id=cand.parcel_id,
            watchlist_id=cand.watchlist_id,
            session=session,
            client=anthropic_client,
        )
        if screened is None or not screened.material:
            continue

        trace = await _maybe_run_tier2(
            cand_event_id=cand.event_id,
            cand_parcel_id=cand.parcel_id,
            cand_watchlist_id=cand.watchlist_id,
            session=session,
            screened=screened,
            client=anthropic_client,
        )
        if trace is not None:
            trace_json = trace.model_dump_json()
            tier = "sonnet"
        else:
            trace_json = _PLACEHOLDER_TRACE
            tier = "haiku"

        dedupe = alert_dedupe_key(
            event_meta["source"], event_meta["external_id"], cand.parcel_id
        )
        result = await session.execute(
            _INSERT_ALERT_SQL,
            {
                "wl": str(cand.watchlist_id),
                "pid": str(cand.parcel_id),
                "eid": str(cand.event_id),
                "axis": screened.axis,
                "score": screened.materiality_score,
                "conf": screened.confidence,
                "summary": screened.summary,
                "trace": trace_json,
                "tier": tier,
                "dedupe": dedupe,
            },
        )
        if result.fetchone() is not None:
            written += 1
        await session.commit()

    return written


async def classify_events(
    event_ids: Sequence[UUID],
    *,
    anthropic_client: anthropic.AsyncAnthropic | None = None,
) -> int:
    """Classify a batch of events. Each event runs in its own session for isolation."""
    total = 0
    for eid in event_ids:
        async with SessionLocal() as session:
            try:
                total += await classify_event(eid, session, anthropic_client=anthropic_client)
            except Exception:
                log.exception("classify_event failed for event_id=%s", eid)
    return total
