"""Tests for replay provenance tracking (replay_runs table + response fields)."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.materiality.tier1 import cache_key as haiku_cache_key

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-00008888bbbb")
TEST_FIPS = "99991"
PARCEL_WKT = (
    "POLYGON((-100.0005 39.9995, -100.0005 40.0005, "
    "-99.9995 40.0005, -99.9995 39.9995, -100.0005 39.9995))"
)


async def _seed(
    session: AsyncSession, *, occurred_at: datetime, cache_material: bool | None = True
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
                "INSERT INTO watchlists (workspace_id, name, deal_thesis) "
                "VALUES (:ws, 'prov test', 'thesis') RETURNING watchlist_id"
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
                "VALUES ('test_replay_prov', :eid, :h, 'permit.new', '{}'::jsonb, "
                "ST_GeomFromText('POINT(-100 40)', 4326), :occ) RETURNING event_id"
            ),
            {"eid": str(uuid4()), "h": uuid4().bytes, "occ": occurred_at},
        )
    ).scalar_one()
    if cache_material is not None:
        resp = json.dumps(
            {
                "material": cache_material,
                "axis": "permit",
                "materiality_score": 50,
                "confidence": 0.85,
                "summary": "x",
            }
        )
        await session.execute(
            text(
                "INSERT INTO classifier_cache (cache_key, tier, response, cost_usd) "
                "VALUES (:k, 'haiku', CAST(:r AS jsonb), 0.001)"
            ),
            {"k": haiku_cache_key(event_id, parcel_id, 1), "r": resp},
        )
    await session.commit()
    return event_id, parcel_id, wl_id


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db_session: AsyncSession):
    yield
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
        text("DELETE FROM events WHERE source = 'test_replay_prov'")
    )
    await db_session.execute(text("DELETE FROM classifier_cache"))
    await db_session.commit()


async def test_replay_writes_run_row_and_returns_provenance(
    http_client: httpx.AsyncClient, db_session: AsyncSession
):
    now = datetime.now(UTC)
    occurred = now - timedelta(days=5)
    _, _, wl_id = await _seed(db_session, occurred_at=occurred)

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
    assert "run_id" in body
    assert "ran_at" in body
    assert body["duration_ms"] >= 0
    assert body["cache_hit_pct"] == 100.0
    assert len(body["alerts"]) == 1

    row = (
        await db_session.execute(
            text(
                "SELECT alert_count, cache_hit_pct FROM replay_runs "
                "WHERE run_id = :rid"
            ),
            {"rid": body["run_id"]},
        )
    ).mappings().one()
    assert row["alert_count"] == 1
    assert float(row["cache_hit_pct"]) == 100.0


async def test_replay_cache_hit_pct_when_partial_misses(
    http_client: httpx.AsyncClient, db_session: AsyncSession
):
    now = datetime.now(UTC)
    # Two events on the same parcel: one cached, one not.
    occurred_cached = now - timedelta(days=5)
    occurred_uncached = now - timedelta(days=4)
    _, parcel_id, wl_id = await _seed(db_session, occurred_at=occurred_cached)
    # Add a second event on the same parcel without seeding cache.
    await db_session.execute(
        text(
            "INSERT INTO events (source, external_id, payload_hash, event_type, "
            "payload, geometry, occurred_at) "
            "VALUES ('test_replay_prov', :eid, :h, 'permit.new', '{}'::jsonb, "
            "ST_GeomFromText('POINT(-100 40)', 4326), :occ)"
        ),
        {"eid": str(uuid4()), "h": uuid4().bytes, "occ": occurred_uncached},
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
    # 1 hit + 1 miss = 50%
    assert body["cache_hit_pct"] == 50.0
    assert body["skipped_for_cache_miss"] == 1
    assert len(body["alerts"]) == 1


async def test_replay_empty_window_reports_100_pct_cache(
    http_client: httpx.AsyncClient, db_session: AsyncSession
):
    """No candidates → no lookups → conventionally 100% (avoid div-by-zero)."""
    wl_id = (
        await db_session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis) "
                "VALUES (:ws, 'empty', 'thesis') RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    await db_session.commit()
    now = datetime.now(UTC)

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
    assert body["cache_hit_pct"] == 100.0
