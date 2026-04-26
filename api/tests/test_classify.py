"""Integration tests for the end-to-end classify pipeline.

Anthropic is mocked. Tests cover: alerts written when material, dedupe blocks
duplicate alerts, no-candidates short-circuit, non-material screen writes
nothing, and the daily LLM cost cap halts further calls.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.materiality.classify import (
    alert_dedupe_key,
    classify_event,
    daily_cost_so_far,
)

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-0000cccc0001")
TEST_FIPS = "99997"

# A small parcel polygon centered near (-100.0, 40.0).
PARCEL_WKT = (
    "POLYGON((-100.0005 39.9995, -100.0005 40.0005, "
    "-99.9995 40.0005, -99.9995 39.9995, -100.0005 39.9995))"
)


async def _seed(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
    parcel_id = (
        await session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid, attrs) "
                "VALUES (:f, :apn, "
                f"ST_Multi(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                f"ST_Centroid(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                "'{\"zoning\":\"R5\",\"area_acres\":\"1.5\",\"site_address\":\"123 X\"}'::jsonb"
                ") RETURNING parcel_id"
            ),
            {"f": TEST_FIPS, "apn": f"T-{uuid4()}"},
        )
    ).scalar_one()
    watchlist_id = (
        await session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis) "
                "VALUES (:ws, 'classify test', 'test') RETURNING watchlist_id"
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
                "ST_GeomFromText('POINT(-100 40)', 4326), :occ) RETURNING event_id"
            ),
            {"eid": str(uuid4()), "h": uuid4().bytes, "occ": datetime.now(UTC)},
        )
    ).scalar_one()
    await session.commit()
    return event_id, parcel_id, watchlist_id


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
        text("DELETE FROM events WHERE source = 'test_source'")
    )
    await db_session.execute(text("DELETE FROM classifier_cache"))
    await db_session.commit()


def _fake_client(input_payload: dict) -> SimpleNamespace:
    block = SimpleNamespace(type="tool_use", name="materiality_screen", input=input_payload)
    response = SimpleNamespace(content=[block])
    return SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=response))
    )


MATERIAL = {
    "material": True,
    "axis": "permit",
    "materiality_score": 75,
    "confidence": 0.9,
    "summary": "Material change.",
}
NOT_MATERIAL = {**MATERIAL, "material": False, "materiality_score": 10, "confidence": 0.4}


async def test_writes_alert_when_screen_says_material(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed(db_session)
    written = await classify_event(
        event_id, db_session, anthropic_client=_fake_client(MATERIAL)
    )
    assert written == 1
    row = (
        await db_session.execute(
            text(
                "SELECT axis, materiality_score, classifier_tier, dedupe_key "
                "FROM alerts WHERE watchlist_id = :w"
            ),
            {"w": str(wl_id)},
        )
    ).mappings().one()
    assert row["axis"] == "permit"
    assert row["materiality_score"] == 75
    assert row["classifier_tier"] == "haiku"
    assert str(parcel_id) in row["dedupe_key"]


async def test_writes_no_alert_when_screen_says_not_material(db_session: AsyncSession):
    event_id, _, wl_id = await _seed(db_session)
    written = await classify_event(
        event_id, db_session, anthropic_client=_fake_client(NOT_MATERIAL)
    )
    assert written == 0
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM alerts WHERE watchlist_id = :w"),
            {"w": str(wl_id)},
        )
    ).scalar_one()
    assert count == 0


async def test_alert_dedupe_blocks_second_run(db_session: AsyncSession):
    event_id, _, wl_id = await _seed(db_session)
    client = _fake_client(MATERIAL)
    first = await classify_event(event_id, db_session, anthropic_client=client)
    second = await classify_event(event_id, db_session, anthropic_client=client)
    assert first == 1
    assert second == 0  # dedupe_key UNIQUE constraint blocks the second insert
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM alerts WHERE watchlist_id = :w"),
            {"w": str(wl_id)},
        )
    ).scalar_one()
    assert count == 1


async def test_no_candidates_short_circuits(db_session: AsyncSession):
    # Event in nowhere — no parcel watched there.
    event_id = (
        await db_session.execute(
            text(
                "INSERT INTO events (source, external_id, payload_hash, event_type, "
                "payload, geometry, occurred_at) "
                "VALUES ('test_source', :eid, :h, 'permit.new', '{}'::jsonb, "
                "ST_GeomFromText('POINT(0 0)', 4326), :occ) RETURNING event_id"
            ),
            {"eid": str(uuid4()), "h": uuid4().bytes, "occ": datetime.now(UTC)},
        )
    ).scalar_one()
    await db_session.commit()
    client = _fake_client(MATERIAL)
    written = await classify_event(event_id, db_session, anthropic_client=client)
    assert written == 0
    client.messages.create.assert_not_awaited()


async def test_cost_cap_halts_classification(db_session: AsyncSession):
    event_id, _, _ = await _seed(db_session)
    client = _fake_client(MATERIAL)
    # Pin the cap below any conceivable per-call cost so the very first
    # candidate is rejected before the API call.
    with patch("parcelpulse.materiality.classify.settings.daily_llm_cost_cap_usd", 0.0):
        written = await classify_event(event_id, db_session, anthropic_client=client)
    assert written == 0
    client.messages.create.assert_not_awaited()


def test_alert_dedupe_key_format():
    pid = UUID("00000000-0000-0000-0000-000000000abc")
    assert alert_dedupe_key("multco_permits", "12345", pid) == (
        "multco_permits:12345:00000000-0000-0000-0000-000000000abc"
    )


async def test_daily_cost_so_far_returns_zero_when_no_rows(db_session: AsyncSession):
    assert await daily_cost_so_far(db_session) == 0.0
