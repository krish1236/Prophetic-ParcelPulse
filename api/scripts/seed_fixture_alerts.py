"""Seed plausible fixture alerts so the UI has visible content during dev.

Each alert carries `decision_trace.fixture = true` so the UI can badge them.
We also write the synthetic *events* and *classifier_cache* rows that back
each fixture, so the replay slider (which reads from events + cache, not the
alerts table) shows the same five entries deterministically over any window
that includes their occurred_at.

Run after `scripts/seed_watchlist.py` (so the demo watchlist exists). No
upstream events required — this script writes its own.

Idempotent: re-running upserts the same fixtures by `(watchlist_id, dedupe_key)`
and uses ON CONFLICT for events + classifier_cache.
"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text

from parcelpulse.db import SessionLocal
from parcelpulse.materiality.tier1 import cache_key as tier1_cache_key
from parcelpulse.materiality.tier2 import cache_key as tier2_cache_key

DEMO_WATCHLIST_ID = UUID("00000000-0000-0000-0000-000000000001")

# Tier-2 fires above this score (mirrors materiality.classify.TIER2_MATERIALITY_THRESHOLD).
TIER2_THRESHOLD = 60

FIXTURES: list[dict] = [
    {
        "dedupe": "fixture:permit:demolition",
        "axis": "permit",
        "event_type": "permit.demolition",
        "materiality_score": 82,
        "confidence": 0.9,
        "summary": "Demolition permit issued on adjacent parcel — assemblage signal.",
        "next_step": "Reach out to demolition applicant before re-listing window opens.",
        "urgency": "this_week",
        "occurred_offset_days": 5,
    },
    {
        "dedupe": "fixture:flood:critical",
        "axis": "flood",
        "event_type": "flood.lomr",
        "materiality_score": 95,
        "confidence": 0.95,
        "summary": "FEMA NFHL revision puts ~30% of buildable area in SFHA Zone AE.",
        "next_step": "Re-run yield with reduced buildable footprint; flag for diligence.",
        "urgency": "now",
        "occurred_offset_days": 8,
    },
    {
        "dedupe": "fixture:zoning:amendment",
        "axis": "zoning",
        "event_type": "zoning.amendment",
        "materiality_score": 65,
        "confidence": 0.75,
        "summary": "Pending zoning text amendment may reduce max ADU count.",
        "next_step": "Confirm hearing date; subscribe to council agenda.",
        "urgency": "this_week",
        "occurred_offset_days": 12,
    },
    {
        "dedupe": "fixture:ownership:llc",
        "axis": "ownership",
        "event_type": "ownership.deed",
        "materiality_score": 35,
        "confidence": 0.6,
        "summary": "LLC owner filed new mailing address — possible disposition signal.",
        "next_step": "Send unsolicited LOI; track for listing within 60 days.",
        "urgency": "fyi",
        "occurred_offset_days": 16,
    },
    {
        "dedupe": "fixture:market:comp",
        "axis": "market",
        "event_type": "market.comp",
        "materiality_score": 55,
        "confidence": 0.7,
        "summary": "Comparable parcel 2 blocks east closed at $312/sqft, below thesis.",
        "next_step": "Refresh underwriting comps; consider re-pricing.",
        "urgency": "this_week",
        "occurred_offset_days": 20,
    },
]


def _payload_hash(external_id: str, payload: dict) -> bytes:
    h = hashlib.sha256()
    h.update(external_id.encode())
    h.update(b"\0")
    h.update(json.dumps(payload, sort_keys=True).encode())
    return h.digest()


async def seed() -> None:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT p.parcel_id "
                    "FROM watched_parcels wp "
                    "JOIN parcels p ON p.parcel_id = wp.parcel_id "
                    "WHERE wp.watchlist_id = :w "
                    "ORDER BY p.parcel_id LIMIT 5"
                ),
                {"w": str(DEMO_WATCHLIST_ID)},
            )
        ).all()
        parcel_ids = [r[0] for r in rows]
        if len(parcel_ids) < 5:
            print(
                f"need >=5 watched parcels; got {len(parcel_ids)}; "
                "run scripts/seed_watchlist.py first"
            )
            return

        thesis_version = (
            await session.execute(
                text("SELECT thesis_version FROM watchlists WHERE watchlist_id = :w"),
                {"w": str(DEMO_WATCHLIST_ID)},
            )
        ).scalar_one()

        now = datetime.now(UTC)

        for i, fa in enumerate(FIXTURES):
            parcel_id = parcel_ids[i % len(parcel_ids)]
            external_id = f"seed:{fa['dedupe']}"
            occurred_at = now - timedelta(days=fa["occurred_offset_days"])
            payload = {
                "fixture": True,
                "axis": fa["axis"],
                "summary": fa["summary"],
            }
            payload_hash = _payload_hash(external_id, payload)

            event_id = (
                await session.execute(
                    text("""
                        INSERT INTO events (
                            source, external_id, payload_hash, event_type,
                            payload, geometry, occurred_at
                        )
                        SELECT
                            'fixture_seed', :ext, :ph, :et,
                            CAST(:pl AS jsonb),
                            p.centroid,
                            :occ
                        FROM parcels p
                        WHERE p.parcel_id = :pid
                        ON CONFLICT (source, external_id, payload_hash)
                        DO UPDATE SET event_type = EXCLUDED.event_type
                        RETURNING event_id
                    """),
                    {
                        "ext": external_id,
                        "ph": payload_hash,
                        "et": fa["event_type"],
                        "pl": json.dumps(payload),
                        "occ": occurred_at,
                        "pid": str(parcel_id),
                    },
                )
            ).scalar_one()

            tier1_response = {
                "material": True,
                "axis": fa["axis"],
                "materiality_score": fa["materiality_score"],
                "confidence": fa["confidence"],
                "summary": fa["summary"],
            }
            await session.execute(
                text("""
                    INSERT INTO classifier_cache (cache_key, tier, response, cost_usd)
                    VALUES (:k, 'haiku', CAST(:r AS jsonb), 0)
                    ON CONFLICT (cache_key) DO UPDATE SET response = EXCLUDED.response
                """),
                {
                    "k": tier1_cache_key(event_id, parcel_id, thesis_version),
                    "r": json.dumps(tier1_response),
                },
            )

            if fa["materiality_score"] >= TIER2_THRESHOLD:
                tier2_response = {
                    "what_changed": fa["summary"],
                    "why_it_matters": (
                        "Fixture trace — pre-seeded so the demo and replay slider "
                        "have visible content without burning live LLM calls."
                    ),
                    "evidence": [
                        {
                            "label": "fixture source",
                            "source_url": f"https://example.com/source/fixture_seed/{external_id}",
                            "snippet": "Synthetic evidence record for UI development.",
                            "captured_at": None,
                        }
                    ],
                    "next_step": {
                        "action": fa["next_step"],
                        "urgency": fa["urgency"],
                        "owner_role": "land_acquisition_lead",
                    },
                }
                await session.execute(
                    text("""
                        INSERT INTO classifier_cache (cache_key, tier, response, cost_usd)
                        VALUES (:k, 'sonnet', CAST(:r AS jsonb), 0)
                        ON CONFLICT (cache_key) DO UPDATE SET response = EXCLUDED.response
                    """),
                    {
                        "k": tier2_cache_key(event_id, parcel_id, thesis_version),
                        "r": json.dumps(tier2_response),
                    },
                )

            trace = {
                "fixture": True,
                "what_changed": fa["summary"],
                "why_it_matters": "(fixture data — for UI development; not LLM-generated)",
                "evidence": [
                    {
                        "label": "fixture source",
                        "source_url": f"https://example.com/source/fixture_seed/{external_id}",
                        "snippet": "Synthetic evidence record for UI development.",
                        "captured_at": None,
                    }
                ],
                "next_step": {
                    "action": fa["next_step"],
                    "urgency": fa["urgency"],
                    "owner_role": "land_acquisition_lead",
                },
            }
            classifier_tier = (
                "sonnet" if fa["materiality_score"] >= TIER2_THRESHOLD else "haiku"
            )
            await session.execute(
                text("""
                    INSERT INTO alerts (
                        watchlist_id, parcel_id, triggering_event_id, axis,
                        materiality_score, confidence, summary, decision_trace,
                        classifier_tier, dedupe_key
                    )
                    VALUES (
                        :w, :p, :e, :ax, :s, :c, :sum,
                        CAST(:t AS jsonb), :tier, :d
                    )
                    ON CONFLICT (watchlist_id, dedupe_key) DO UPDATE SET
                        materiality_score = EXCLUDED.materiality_score,
                        confidence = EXCLUDED.confidence,
                        summary = EXCLUDED.summary,
                        decision_trace = EXCLUDED.decision_trace,
                        classifier_tier = EXCLUDED.classifier_tier
                """),
                {
                    "w": str(DEMO_WATCHLIST_ID),
                    "p": str(parcel_id),
                    "e": str(event_id),
                    "ax": fa["axis"],
                    "s": fa["materiality_score"],
                    "c": fa["confidence"],
                    "sum": fa["summary"],
                    "t": json.dumps(trace),
                    "tier": classifier_tier,
                    "d": fa["dedupe"],
                },
            )

        await session.commit()

        total = (
            await session.execute(
                text(
                    "SELECT count(*) FROM alerts "
                    "WHERE watchlist_id = :w "
                    "  AND decision_trace->>'fixture' = 'true'"
                ),
                {"w": str(DEMO_WATCHLIST_ID)},
            )
        ).scalar_one()
        print(f"watchlist={DEMO_WATCHLIST_ID} fixture_alerts_total={total}")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
