"""Tests for watchlist creation + add-parcels endpoints."""

from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.routes.watchlists import ANONYMOUS_WORKSPACE_ID

TEST_FIPS = "41051"  # use real Multnomah for the apn-resolution path


@pytest_asyncio.fixture
async def created_watchlist(http_client: httpx.AsyncClient, db_session: AsyncSession):
    r = await http_client.post(
        "/watchlists",
        json={
            "name": "create-test",
            "deal_thesis": "Townhomes 8-12 du/ac in central Portland.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    yield UUID(body["watchlist_id"])
    await db_session.execute(
        text("DELETE FROM replay_runs WHERE watchlist_id = :w"),
        {"w": body["watchlist_id"]},
    )
    await db_session.execute(
        text("DELETE FROM watched_parcels WHERE watchlist_id = :w"),
        {"w": body["watchlist_id"]},
    )
    await db_session.execute(
        text("DELETE FROM watchlists WHERE watchlist_id = :w"),
        {"w": body["watchlist_id"]},
    )
    await db_session.commit()


async def test_create_watchlist_returns_uuid_and_zero_counts(
    http_client: httpx.AsyncClient, db_session: AsyncSession
):
    r = await http_client.post(
        "/watchlists",
        json={
            "name": "smoke",
            "deal_thesis": "Townhomes 8-12 du/ac, must clear flood zone.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert UUID(body["watchlist_id"])
    assert body["name"] == "smoke"
    assert body["parcel_count"] == 0
    assert body["alert_count"] == 0

    # Workspace stamped to the anonymous one.
    ws = (
        await db_session.execute(
            text("SELECT workspace_id FROM watchlists WHERE watchlist_id = :w"),
            {"w": body["watchlist_id"]},
        )
    ).scalar_one()
    assert ws == ANONYMOUS_WORKSPACE_ID
    # cleanup
    await db_session.execute(
        text("DELETE FROM watchlists WHERE watchlist_id = :w"),
        {"w": body["watchlist_id"]},
    )
    await db_session.commit()


async def test_create_watchlist_rejects_short_thesis(http_client: httpx.AsyncClient):
    r = await http_client.post(
        "/watchlists", json={"name": "x", "deal_thesis": "too short"}
    )
    assert r.status_code == 422


async def test_get_watchlist_returns_404_for_unknown(http_client: httpx.AsyncClient):
    r = await http_client.get(f"/watchlists/{uuid4()}")
    assert r.status_code == 404


async def test_add_parcels_by_apn_resolves_and_skips_unknown(
    http_client: httpx.AsyncClient, created_watchlist
):
    # Mix one real Multnomah APN with one bogus one.
    r = await http_client.post(
        f"/watchlists/{created_watchlist}/parcels",
        json={"apns": ["1S1E03CD  -00800", "DOES-NOT-EXIST"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 1
    assert body["not_found"] == 1
    assert body["total_watched"] == 1


async def test_add_parcels_by_apn_is_idempotent(
    http_client: httpx.AsyncClient, created_watchlist
):
    payload = {"apns": ["1S1E03CD  -00800"]}
    a = await http_client.post(f"/watchlists/{created_watchlist}/parcels", json=payload)
    b = await http_client.post(f"/watchlists/{created_watchlist}/parcels", json=payload)
    assert a.json()["added"] == 1
    assert b.json()["added"] == 0
    assert b.json()["total_watched"] == 1


async def test_add_parcels_by_polygon_resolves_intersecting(
    http_client: httpx.AsyncClient, created_watchlist
):
    # Tight bbox over downtown Portland: encloses a handful of CX parcels.
    polygon = {
        "type": "Polygon",
        "coordinates": [[
            [-122.6800, 45.5200],
            [-122.6800, 45.5260],
            [-122.6700, 45.5260],
            [-122.6700, 45.5200],
            [-122.6800, 45.5200],
        ]],
    }
    r = await http_client.post(
        f"/watchlists/{created_watchlist}/parcels", json={"polygon": polygon}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["added"] >= 1  # downtown has lots of parcels
    assert body["total_watched"] == body["added"]


async def test_add_parcels_requires_apns_or_polygon(
    http_client: httpx.AsyncClient, created_watchlist
):
    r = await http_client.post(
        f"/watchlists/{created_watchlist}/parcels", json={}
    )
    assert r.status_code == 400


async def test_add_parcels_404_for_unknown_watchlist(http_client: httpx.AsyncClient):
    r = await http_client.post(
        f"/watchlists/{uuid4()}/parcels",
        json={"apns": ["1S1E03CD  -00800"]},
    )
    assert r.status_code == 404


async def test_get_watchlist_returns_counts_after_adds(
    http_client: httpx.AsyncClient, created_watchlist
):
    await http_client.post(
        f"/watchlists/{created_watchlist}/parcels",
        json={"apns": ["1S1E03CD  -00800", "1N1E35AB  -07101"]},
    )
    r = await http_client.get(f"/watchlists/{created_watchlist}")
    body = r.json()
    assert body["parcel_count"] == 2
    assert body["alert_count"] == 0
