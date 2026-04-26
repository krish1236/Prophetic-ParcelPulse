"""End-to-end classification pipeline: event → Tier 0 → Tier 1 → alerts.

For each candidate produced by Tier 0, this worker calls Tier 1 and (if the
event is material) writes an alert. Two-layer dedupe is enforced:
  * event-layer: (source, external_id, payload_hash) UNIQUE on `events`
  * alert-layer: (watchlist_id, dedupe_key) UNIQUE on `alerts`

Tier 1 calls are gated by a daily LLM spend cap. Once today's classifier
spend hits `settings.daily_llm_cost_cap_usd`, the worker stops calling Haiku
and skips remaining candidates (they stay in the events log for later runs).

Phase 5 will plug in Tier 2 (Sonnet decision trace) below the same gate;
for now we write a placeholder JSON to alerts.decision_trace.
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
from parcelpulse.materiality.tier1 import screen
from parcelpulse.settings import settings

log = logging.getLogger(__name__)


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
        CAST(:trace AS jsonb), 'haiku', :dedupe
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


async def classify_event(
    event_id: UUID,
    session: AsyncSession,
    *,
    anthropic_client: anthropic.AsyncAnthropic | None = None,
) -> int:
    """Run Tier 0 → Tier 1 for one event; write alerts. Returns alerts inserted."""
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
                # Phase 5 will replace this placeholder with a Sonnet decision trace.
                "trace": '{"placeholder": true, "tier": "haiku"}',
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
