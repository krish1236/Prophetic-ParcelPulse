"""Canonical end-to-end smoke test (CI gate).

Builds a tiny world (parcel + watchlist + watched_parcel + ingested event +
pre-seeded Tier 1 cache) and runs the classifier. Asserts an alert lands
within seconds. If this test fails, the engine is broken — fail CI loudly.

Doesn't call the live LLM: the cache pre-seed is what makes Tier 1 short-
circuit. Same property the Phase 7 replay slider relies on.
"""

import asyncio
import json
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.materiality.classify import classify_events
from parcelpulse.materiality.tier1 import cache_key

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-0000ffffffff")
TEST_FIPS = "99990"
SMOKE_TIMEOUT_SECONDS = 60.0
PARCEL_WKT = (
    "POLYGON((-100.0005 39.9995, -100.0005 40.0005, "
    "-99.9995 40.0005, -99.9995 39.9995, -100.0005 39.9995))"
)


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db_session: AsyncSession):
    yield
    await db_session.execute(
        text(
            "DELETE FROM alerts WHERE watchlist_id IN "
            "(SELECT watchlist_id FROM watchlists WHERE workspace_id = :ws)"
        ),
        {"ws": str(TEST_WORKSPACE)},
    )
    await db_session.execute(
        text(
            "DELETE FROM watched_parcels WHERE watchlist_id IN "
            "(SELECT watchlist_id FROM watchlists WHERE workspace_id = :ws)"
        ),
        {"ws": str(TEST_WORKSPACE)},
    )
    await db_session.execute(
        text("DELETE FROM watchlists WHERE workspace_id = :ws"),
        {"ws": str(TEST_WORKSPACE)},
    )
    await db_session.execute(
        text("DELETE FROM parcels WHERE county_fips = :f"), {"f": TEST_FIPS}
    )
    await db_session.execute(
        text("DELETE FROM events WHERE source = 'test_smoke'")
    )
    await db_session.execute(text("DELETE FROM classifier_cache"))
    await db_session.commit()


async def test_smoke_event_to_alert_within_60s(db_session: AsyncSession):
    parcel_id = (
        await db_session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid) "
                f"VALUES (:f, 'SMOKE', ST_Multi(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                f"ST_Centroid(ST_GeomFromText('{PARCEL_WKT}', 4326))) RETURNING parcel_id"
            ),
            {"f": TEST_FIPS},
        )
    ).scalar_one()
    wl_id = (
        await db_session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis, thesis_version) "
                "VALUES (:ws, 'smoke', 'thesis', 1) RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO watched_parcels (watchlist_id, parcel_id) VALUES (:w, :p)"),
        {"w": str(wl_id), "p": str(parcel_id)},
    )
    event_id = (
        await db_session.execute(
            text(
                "INSERT INTO events (source, external_id, payload_hash, event_type, "
                "payload, geometry, occurred_at) "
                "VALUES ('test_smoke', :eid, :h, 'permit.new', '{}'::jsonb, "
                "ST_GeomFromText('POINT(-100 40)', 4326), :occ) RETURNING event_id"
            ),
            {"eid": str(uuid4()), "h": uuid4().bytes, "occ": datetime.now(UTC)},
        )
    ).scalar_one()
    # Score 50 stays below TIER2_MATERIALITY_THRESHOLD (60), so Tier 2 (Sonnet)
    # never fires and the smoke path needs no Sonnet cache pre-seed.
    response = json.dumps({
        "material": True,
        "axis": "permit",
        "materiality_score": 50,
        "confidence": 0.9,
        "summary": "Smoke alert: permit fires.",
    })
    await db_session.execute(
        text(
            "INSERT INTO classifier_cache (cache_key, tier, response, cost_usd) "
            "VALUES (:k, 'haiku', CAST(:r AS jsonb), 0.001)"
        ),
        {"k": cache_key(event_id, parcel_id, 1), "r": response},
    )
    await db_session.commit()

    start = time.monotonic()
    written = await asyncio.wait_for(classify_events([event_id]), timeout=SMOKE_TIMEOUT_SECONDS)
    elapsed = time.monotonic() - start
    assert written >= 1, "smoke: classifier did not write any alerts"
    assert elapsed < SMOKE_TIMEOUT_SECONDS

    alert_count = (
        await db_session.execute(
            text("SELECT count(*) FROM alerts WHERE watchlist_id = :w"),
            {"w": str(wl_id)},
        )
    ).scalar_one()
    assert alert_count >= 1
