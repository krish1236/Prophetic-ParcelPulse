from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.adapters.base import CanonicalEvent
from parcelpulse.ingest import insert_events

TEST_SOURCE = "test_ingest"


def _ev(external_id: str, payload: dict | None = None) -> CanonicalEvent:
    return CanonicalEvent(
        source=TEST_SOURCE,
        external_id=external_id,
        event_type="test.event",
        payload=payload or {"value": 1},
        geometry={"type": "Point", "coordinates": [-122.6, 45.5]},
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest_asyncio.fixture(autouse=True)
async def _clean_test_events(db_session: AsyncSession):
    yield
    await db_session.execute(
        text("DELETE FROM events WHERE source = :s"), {"s": TEST_SOURCE}
    )
    await db_session.commit()


async def test_insert_events_empty_returns_empty_list():
    assert await insert_events([]) == []


async def test_insert_events_inserts_new_rows(db_session: AsyncSession):
    events = [_ev(str(uuid4())) for _ in range(3)]
    new_ids = await insert_events(events)
    assert len(new_ids) == 3
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM events WHERE source = :s"), {"s": TEST_SOURCE}
        )
    ).scalar_one()
    assert count == 3


async def test_insert_events_is_idempotent(db_session: AsyncSession):
    events = [_ev(str(uuid4())) for _ in range(3)]
    first = await insert_events(events)
    second = await insert_events(events)
    assert len(first) == 3
    assert len(second) == 0
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM events WHERE source = :s"), {"s": TEST_SOURCE}
        )
    ).scalar_one()
    assert count == 3


async def test_insert_events_treats_payload_change_as_new(db_session: AsyncSession):
    ext = str(uuid4())
    first = await insert_events([_ev(ext, payload={"value": 1})])
    second = await insert_events([_ev(ext, payload={"value": 2})])
    assert len(first) == 1
    # Different payload_hash → different row, not a conflict.
    assert len(second) == 1


async def test_insert_events_persists_geometry(db_session: AsyncSession):
    ext = str(uuid4())
    await insert_events([_ev(ext)])
    geom_text = (
        await db_session.execute(
            text("SELECT ST_AsText(geometry) FROM events WHERE external_id = :e"),
            {"e": ext},
        )
    ).scalar_one()
    assert geom_text == "POINT(-122.6 45.5)"
