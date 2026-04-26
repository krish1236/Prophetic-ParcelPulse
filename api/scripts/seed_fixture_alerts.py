"""Seed plausible fixture alerts so the UI has visible content during dev.

Each alert carries `decision_trace.fixture = true` so the UI can badge them.
Run after `scripts/seed_watchlist.py` (so the demo watchlist exists) and
after at least 5 events have been ingested (so we have something to point at
for triggering_event_id).

Idempotent: re-running upserts the same fixtures by `(watchlist_id, dedupe_key)`.
"""

import asyncio
import json
from uuid import UUID

from sqlalchemy import text

from parcelpulse.db import SessionLocal

DEMO_WATCHLIST_ID = UUID("00000000-0000-0000-0000-000000000001")

FIXTURES: list[dict] = [
    {
        "dedupe": "fixture:permit:demolition",
        "axis": "permit",
        "materiality_score": 82,
        "confidence": 0.9,
        "summary": "Demolition permit issued on adjacent parcel — assemblage signal.",
        "next_step": "Reach out to demolition applicant before re-listing window opens.",
        "urgency": "this_week",
    },
    {
        "dedupe": "fixture:flood:critical",
        "axis": "flood",
        "materiality_score": 95,
        "confidence": 0.95,
        "summary": "FEMA NFHL revision puts ~30% of buildable area in SFHA Zone AE.",
        "next_step": "Re-run yield with reduced buildable footprint; flag for diligence.",
        "urgency": "now",
    },
    {
        "dedupe": "fixture:zoning:amendment",
        "axis": "zoning",
        "materiality_score": 65,
        "confidence": 0.75,
        "summary": "Pending zoning text amendment may reduce max ADU count.",
        "next_step": "Confirm hearing date; subscribe to council agenda.",
        "urgency": "this_week",
    },
    {
        "dedupe": "fixture:ownership:llc",
        "axis": "ownership",
        "materiality_score": 35,
        "confidence": 0.6,
        "summary": "LLC owner filed new mailing address — possible disposition signal.",
        "next_step": "Send unsolicited LOI; track for listing within 60 days.",
        "urgency": "fyi",
    },
    {
        "dedupe": "fixture:market:comp",
        "axis": "market",
        "materiality_score": 55,
        "confidence": 0.7,
        "summary": "Comparable parcel 2 blocks east closed at $312/sqft, below thesis.",
        "next_step": "Refresh underwriting comps; consider re-pricing.",
        "urgency": "this_week",
    },
]


async def seed() -> None:
    async with SessionLocal() as session:
        parcel_ids = [
            r[0]
            for r in (
                await session.execute(
                    text(
                        "SELECT parcel_id FROM watched_parcels "
                        "WHERE watchlist_id = :w ORDER BY parcel_id LIMIT 5"
                    ),
                    {"w": str(DEMO_WATCHLIST_ID)},
                )
            ).all()
        ]
        if len(parcel_ids) < 5:
            print(
                f"need >=5 watched parcels; got {len(parcel_ids)}; "
                "run scripts/seed_watchlist.py first"
            )
            return

        event_ids = [
            r[0]
            for r in (
                await session.execute(
                    text("SELECT event_id FROM events ORDER BY ingested_at DESC LIMIT 5")
                )
            ).all()
        ]
        if len(event_ids) < 5:
            print(
                f"need >=5 events; got {len(event_ids)}; "
                "run scheduler or scripts/load_parcels.py + scheduler first"
            )
            return

        for i, fa in enumerate(FIXTURES):
            trace = {
                "fixture": True,
                "what_changed": fa["summary"],
                "why_it_matters": "(fixture data — for UI development; not LLM-generated)",
                "evidence": [
                    {
                        "label": "fixture source",
                        "source_url": "https://example.com/fixture",
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
                    INSERT INTO alerts (
                        watchlist_id, parcel_id, triggering_event_id, axis,
                        materiality_score, confidence, summary, decision_trace,
                        classifier_tier, dedupe_key
                    )
                    VALUES (
                        :w, :p, :e, :ax, :s, :c, :sum,
                        CAST(:t AS jsonb), 'haiku', :d
                    )
                    ON CONFLICT (watchlist_id, dedupe_key) DO UPDATE SET
                        materiality_score = EXCLUDED.materiality_score,
                        confidence = EXCLUDED.confidence,
                        summary = EXCLUDED.summary,
                        decision_trace = EXCLUDED.decision_trace
                """),
                {
                    "w": str(DEMO_WATCHLIST_ID),
                    "p": str(parcel_ids[i % len(parcel_ids)]),
                    "e": str(event_ids[i % len(event_ids)]),
                    "ax": fa["axis"],
                    "s": fa["materiality_score"],
                    "c": fa["confidence"],
                    "sum": fa["summary"],
                    "t": json.dumps(trace),
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
