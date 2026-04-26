"""Tests for the replay engine + POST /replay endpoint.

The whole point of replay is determinism: same inputs → same alerts, no live
LLM calls. Tests use the cache directly to seed deterministic responses, then
verify the engine returns the same alerts on repeat runs.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.materiality.tier1 import cache_key as haiku_cache_key

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-00007777aaaa")
TEST_FIPS = "99992"
PARCEL_WKT = (
    "POLYGON((-100.0005 39.9995, -100.0005 40.0005, "
    "-99.9995 40.0005, -99.9995 39.9995, -100.0005 39.9995))"
)


async def _seed_world(
    session: AsyncSession, *, occurred_at: datetime, material: bool = True
) -> tuple[UUID, UUID, UUID]:
    parcel_id = (
        await session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid) "
                f"VALUES (:f, :apn, ST_Multi(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                f"ST_Centroid(ST_GeomFromText('{PARCEL_WKT}', 4326))) RETURNING parcel_id"
            ),
            {"f": TEST_FIPS, "apn": f"R-{uuid4()}"},
        )
    ).scalar_one()
    wl_id = (
        await session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis, thesis_version) "
                "VALUES (:ws, 'replay test', 'thesis', 1) RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    await session.execute(
        text("INSERT INTO watched_parcels (watchlist_id, parcel_id) VALUES (:w, :p)"),
        {"w": str(wl_id), "p": str(parcel_id)},
    )
    event_id = (
        await session.execute(
            text(
                "INSERT INTO events (source, external_id, payload_hash, event_type, "
                "payload, geometry, occurred_at) "
                "VALUES ('test_replay', :eid, :h, 'permit.new', '{}'::jsonb, "
                "ST_GeomFromText('POINT(-100 40)', 4326), :occ) RETURNING event_id"
            ),
            {"eid": str(uuid4()), "h": uuid4().bytes, "occ": occurred_at},
        )
    ).scalar_one()
    # Pre-seed Tier 1 cache so cache-only replay can succeed.
    response = {
        "material": material,
        "axis": "permit",
        "materiality_score": 50,  # below TIER2 threshold → no Sonnet lookup needed
        "confidence": 0.85,
        "summary": "Material change." if material else "Not material.",
    }
    await session.execute(
        text(
            "INSERT INTO classifier_cache (cache_key, tier, response, cost_usd) "
            "VALUES (:k, 'haiku', CAST(:r AS jsonb), 0.001)"
        ),
        {
            "k": haiku_cache_key(event_id, parcel_id, 1),
            "r": json.dumps(response),
        },
    )
    await session.commit()
    return event_id, parcel_id, wl_id


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db_session: AsyncSession):
    yield
    # replay_runs FK references watchlists; delete it first.
    await db_session.execute(
        text(
            "DELETE FROM replay_runs WHERE watchlist_id IN "
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
        text("DELETE FROM events WHERE source = 'test_replay'")
    )
    await db_session.execute(text("DELETE FROM classifier_cache"))
    await db_session.commit()


async def test_replay_returns_alerts_for_cached_material_event(
    http_client: httpx.AsyncClient, db_session: AsyncSession
):
    now = datetime.now(UTC)
    occurred = now - timedelta(days=10)
    _, _, wl_id = await _seed_world(db_session, occurred_at=occurred)

    r = await http_client.post(
        "/replay",
        json={
            "watchlist_id": str(wl_id),
            "from_ts": (now - timedelta(days=30)).isoformat(),
            "to_ts": now.isoformat(),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["alerts"]) == 1
    assert body["alerts"][0]["axis"] == "permit"
    assert body["alerts"][0]["classifier_tier"] == "haiku"
    assert body["skipped_for_cache_miss"] == 0
    assert body["candidate_total"] == 1


async def test_replay_is_deterministic_across_runs(
    http_client: httpx.AsyncClient, db_session: AsyncSession
):
    now = datetime.now(UTC)
    occurred = now - timedelta(days=5)
    _, _, wl_id = await _seed_world(db_session, occurred_at=occurred)

    payload = {
        "watchlist_id": str(wl_id),
        "from_ts": (now - timedelta(days=30)).isoformat(),
        "to_ts": now.isoformat(),
    }
    a = (await http_client.post("/replay", json=payload)).json()
    b = (await http_client.post("/replay", json=payload)).json()
    assert a["alerts"] == b["alerts"]


async def test_replay_skips_uncached_events_and_reports_count(
    http_client: httpx.AsyncClient, db_session: AsyncSession
):
    now = datetime.now(UTC)
    # Insert a parcel + watchlist + event but DON'T pre-seed cache for the event.
    parcel_id = (
        await db_session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid) "
                f"VALUES (:f, 'NOCACHE', ST_Multi(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                f"ST_Centroid(ST_GeomFromText('{PARCEL_WKT}', 4326))) RETURNING parcel_id"
            ),
            {"f": TEST_FIPS},
        )
    ).scalar_one()
    wl_id = (
        await db_session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis) "
                "VALUES (:ws, 'replay nocache', 'thesis') RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO watched_parcels (watchlist_id, parcel_id) VALUES (:w, :p)"),
        {"w": str(wl_id), "p": str(parcel_id)},
    )
    await db_session.execute(
        text(
            "INSERT INTO events (source, external_id, payload_hash, event_type, "
            "payload, geometry, occurred_at) "
            "VALUES ('test_replay', :eid, :h, 'permit.new', '{}'::jsonb, "
            "ST_GeomFromText('POINT(-100 40)', 4326), :occ)"
        ),
        {
            "eid": str(uuid4()),
            "h": uuid4().bytes,
            "occ": now - timedelta(days=2),
        },
    )
    await db_session.commit()

    r = await http_client.post(
        "/replay",
        json={
            "watchlist_id": str(wl_id),
            "from_ts": (now - timedelta(days=30)).isoformat(),
            "to_ts": now.isoformat(),
        },
    )
    body = r.json()
    assert body["alerts"] == []
    assert body["skipped_for_cache_miss"] == 1
    assert body["candidate_total"] == 1


async def test_replay_filters_events_outside_window(
    http_client: httpx.AsyncClient, db_session: AsyncSession
):
    now = datetime.now(UTC)
    # Event 100 days ago, window is last 30 days → should be excluded.
    occurred = now - timedelta(days=100)
    _, _, wl_id = await _seed_world(db_session, occurred_at=occurred)

    r = await http_client.post(
        "/replay",
        json={
            "watchlist_id": str(wl_id),
            "from_ts": (now - timedelta(days=30)).isoformat(),
            "to_ts": now.isoformat(),
        },
    )
    body = r.json()
    assert body["alerts"] == []
    assert body["candidate_total"] == 0


async def test_replay_skips_non_material_screens(
    http_client: httpx.AsyncClient, db_session: AsyncSession
):
    now = datetime.now(UTC)
    occurred = now - timedelta(days=5)
    _, _, wl_id = await _seed_world(db_session, occurred_at=occurred, material=False)

    r = await http_client.post(
        "/replay",
        json={
            "watchlist_id": str(wl_id),
            "from_ts": (now - timedelta(days=30)).isoformat(),
            "to_ts": now.isoformat(),
        },
    )
    body = r.json()
    assert body["alerts"] == []
    assert body["candidate_total"] == 1
    assert body["skipped_for_cache_miss"] == 0
