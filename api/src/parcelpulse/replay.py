"""Replay engine — re-run the materiality pipeline over a historical window.

Pure cache-only mode: every Tier 1 / Tier 2 lookup is a `use_cache_only=True`
call against `classifier_cache`. We never call the live LLM during replay,
which makes results free *and* deterministic. The Phase 7 replay slider
depends on this property.

Each run writes a `replay_runs` row (run_id, watchlist_id, window, alert_count,
cache_hit_pct, ran_at) so the UI can show provenance under the slider —
"ran in 320ms · 87% cache hit · 14 alerts" — and so future audits can compare
replays side-by-side.

Cache misses (events that were never classified live, or for which the
watchlist's thesis_version has bumped) are reported in the response so the
UI can show "N alert candidates skipped — not classified at the time"
without silently dropping them.
"""

import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.materiality.classify import (
    TIER2_MATERIALITY_THRESHOLD,
    alert_dedupe_key,
)
from parcelpulse.materiality.tier0 import find_candidates
from parcelpulse.materiality.tier1 import screen
from parcelpulse.materiality.tier2 import generate_trace


async def replay_window(
    *,
    watchlist_id: UUID,
    from_ts: datetime,
    to_ts: datetime,
    session: AsyncSession,
) -> dict[str, Any]:
    started = time.monotonic()
    event_rows = (
        await session.execute(
            text("""
                SELECT event_id, source, external_id, occurred_at
                FROM events
                WHERE occurred_at >= :from_ts AND occurred_at < :to_ts
                ORDER BY occurred_at DESC
            """),
            {"from_ts": from_ts, "to_ts": to_ts},
        )
    ).mappings().all()

    seen_dedupe: set[str] = set()
    alerts: list[dict[str, Any]] = []
    candidate_total = 0
    cache_hits = 0
    cache_misses = 0

    for ev in event_rows:
        candidates = [
            c
            for c in await find_candidates(ev["event_id"], session)
            if c.watchlist_id == watchlist_id
        ]
        candidate_total += len(candidates)

        for cand in candidates:
            screened = await screen(
                event_id=cand.event_id,
                parcel_id=cand.parcel_id,
                watchlist_id=cand.watchlist_id,
                session=session,
                use_cache_only=True,
            )
            if screened is None:
                cache_misses += 1
                continue
            cache_hits += 1
            if not screened.material:
                continue

            tier_label = "haiku"
            if screened.materiality_score >= TIER2_MATERIALITY_THRESHOLD:
                trace = await generate_trace(
                    event_id=cand.event_id,
                    parcel_id=cand.parcel_id,
                    watchlist_id=cand.watchlist_id,
                    session=session,
                    tier1_screen=screened,
                    use_cache_only=True,
                )
                if trace is not None:
                    tier_label = "sonnet"

            dedupe = alert_dedupe_key(
                ev["source"], ev["external_id"], cand.parcel_id
            )
            if dedupe in seen_dedupe:
                continue
            seen_dedupe.add(dedupe)

            apn = (
                await session.execute(
                    text("SELECT apn FROM parcels WHERE parcel_id = :p"),
                    {"p": str(cand.parcel_id)},
                )
            ).scalar_one()

            alerts.append(
                {
                    "event_id": str(ev["event_id"]),
                    "parcel_id": str(cand.parcel_id),
                    "parcel_apn": apn,
                    "axis": screened.axis,
                    "materiality_score": screened.materiality_score,
                    "confidence": screened.confidence,
                    "summary": screened.summary,
                    "classifier_tier": tier_label,
                    "occurred_at": ev["occurred_at"].isoformat(),
                }
            )

    duration_ms = int((time.monotonic() - started) * 1000)
    lookups = cache_hits + cache_misses
    cache_hit_pct = round(cache_hits / lookups * 100, 1) if lookups else 100.0

    run_id = uuid4()
    ran_at = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO replay_runs (
                run_id, watchlist_id, from_ts, to_ts, alert_count, cache_hit_pct, ran_at
            )
            VALUES (:rid, :wl, :from_ts, :to_ts, :ac, :pct, :ran)
        """),
        {
            "rid": str(run_id),
            "wl": str(watchlist_id),
            "from_ts": from_ts,
            "to_ts": to_ts,
            "ac": len(alerts),
            "pct": cache_hit_pct,
            "ran": ran_at,
        },
    )
    await session.commit()

    return {
        "run_id": str(run_id),
        "from_ts": from_ts.isoformat(),
        "to_ts": to_ts.isoformat(),
        "alerts": alerts,
        "candidate_total": candidate_total,
        "skipped_for_cache_miss": cache_misses,
        "cache_hit_pct": cache_hit_pct,
        "duration_ms": duration_ms,
        "ran_at": ran_at.isoformat(),
    }
