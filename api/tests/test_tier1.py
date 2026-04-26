"""Tests for Tier 1 Haiku classifier.

Anthropic calls are mocked end-to-end; tests never touch the live API. We
verify the cache-first path, cache writes after a live response, the
use_cache_only escape hatch, and graceful handling of bad tool output.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.materiality.tier1 import (
    MaterialityScreen,
    cache_key,
    screen,
)

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-0000bbbb0001")
TEST_FIPS = "99998"


async def _seed_world(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
    """Insert a parcel, a watchlist + watched_parcel, and one event. Return ids."""
    parcel_id = (
        await session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid, attrs) "
                "VALUES (:f, :apn, "
                "ST_Multi(ST_GeomFromText('POLYGON((-100 40, -100 40.001, -99.999 40.001, -99.999 40, -100 40))', 4326)), "
                "ST_GeomFromText('POINT(-100 40)', 4326), "
                "'{\"zoning\":\"R5\",\"area_acres\":\"1.5\",\"site_address\":\"123 TEST ST\"}'::jsonb) "
                "RETURNING parcel_id"
            ),
            {"f": TEST_FIPS, "apn": f"T-{uuid4()}"},
        )
    ).scalar_one()

    watchlist_id = (
        await session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis, thesis_version) "
                "VALUES (:ws, 'tier1 test', 'Townhomes 8-12 du/ac.', 1) "
                "RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()

    await session.execute(
        text("INSERT INTO watched_parcels (watchlist_id, parcel_id) VALUES (:w, :p)"),
        {"w": str(watchlist_id), "p": str(parcel_id)},
    )

    event_id = (
        await session.execute(
            text(
                "INSERT INTO events (source, external_id, payload_hash, event_type, "
                "payload, geometry, occurred_at) "
                "VALUES ('test_source', :eid, :h, 'permit.new', "
                "'{\"WORK_TYPE\":\"New Construction\"}'::jsonb, "
                "ST_GeomFromText('POINT(-100 40)', 4326), :occ) "
                "RETURNING event_id"
            ),
            {
                "eid": str(uuid4()),
                "h": uuid4().bytes,
                "occ": datetime.now(UTC),
            },
        )
    ).scalar_one()
    await session.commit()
    return event_id, parcel_id, watchlist_id


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db_session: AsyncSession):
    yield
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
        text("DELETE FROM events WHERE source = 'test_source'")
    )
    await db_session.execute(text("DELETE FROM classifier_cache"))
    await db_session.commit()


def _fake_client(payload: dict) -> AsyncMock:
    """Build an AsyncAnthropic-shaped mock that returns one tool_use block."""
    block = SimpleNamespace(type="tool_use", name="materiality_screen", input=payload)
    response = SimpleNamespace(content=[block])
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=response))
    )
    return client


SCREEN_OK_PAYLOAD = {
    "material": True,
    "axis": "permit",
    "materiality_score": 70,
    "confidence": 0.85,
    "summary": "New construction next door changes yield assumptions.",
}


async def test_calls_anthropic_when_cache_miss(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed_world(db_session)
    client = _fake_client(SCREEN_OK_PAYLOAD)
    result = await screen(event_id, parcel_id, wl_id, db_session, client=client)
    assert isinstance(result, MaterialityScreen)
    assert result.material is True
    assert result.axis == "permit"
    assert result.materiality_score == 70
    client.messages.create.assert_awaited_once()


async def test_returns_cached_response_without_calling_api(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed_world(db_session)
    client = _fake_client(SCREEN_OK_PAYLOAD)

    first = await screen(event_id, parcel_id, wl_id, db_session, client=client)
    assert first is not None
    assert client.messages.create.await_count == 1

    second = await screen(event_id, parcel_id, wl_id, db_session, client=client)
    assert second == first
    assert client.messages.create.await_count == 1  # no new call


async def test_use_cache_only_returns_none_on_miss(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed_world(db_session)
    client = _fake_client(SCREEN_OK_PAYLOAD)
    result = await screen(
        event_id, parcel_id, wl_id, db_session, client=client, use_cache_only=True
    )
    assert result is None
    client.messages.create.assert_not_awaited()


async def test_cache_key_changes_with_thesis_version():
    eid = uuid4()
    pid = uuid4()
    a = cache_key(eid, pid, 1)
    b = cache_key(eid, pid, 2)
    assert a != b


async def test_invalid_tool_output_returns_none(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed_world(db_session)
    bad = {"material": "not-a-bool", "axis": "permit"}  # missing fields, wrong types
    client = _fake_client(bad)
    result = await screen(event_id, parcel_id, wl_id, db_session, client=client)
    assert result is None
    # Cache must NOT be written for bad outputs.
    count = (
        await db_session.execute(text("SELECT count(*) FROM classifier_cache"))
    ).scalar_one()
    assert count == 0


async def test_cache_write_persists_cost(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed_world(db_session)
    client = _fake_client(SCREEN_OK_PAYLOAD)
    await screen(event_id, parcel_id, wl_id, db_session, client=client)
    cost = (
        await db_session.execute(
            text("SELECT cost_usd FROM classifier_cache WHERE tier = 'haiku' LIMIT 1")
        )
    ).scalar_one()
    assert float(cost) > 0
