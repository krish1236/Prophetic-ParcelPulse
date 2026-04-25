from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TEST_SOURCE_FOR_LAG = "multco_permits"


@pytest_asyncio.fixture
async def fresh_test_event(db_session: AsyncSession):
    """Insert a synthetic multco_permits event so /health has fresh data to report."""
    external_id = f"health-test-{uuid4()}"
    occurred = datetime.now(UTC) - timedelta(seconds=5)
    await db_session.execute(
        text(
            "INSERT INTO events "
            "(source, external_id, payload_hash, event_type, payload, occurred_at) "
            "VALUES (:s, :eid, :hash, 'permit.test', '{}'::jsonb, :occ)"
        ),
        {
            "s": TEST_SOURCE_FOR_LAG,
            "eid": external_id,
            "hash": uuid4().bytes,
            "occ": occurred,
        },
    )
    await db_session.commit()
    yield external_id
    await db_session.execute(
        text("DELETE FROM events WHERE external_id = :eid"), {"eid": external_id}
    )
    await db_session.commit()


async def test_health_returns_status_ok(http_client: httpx.AsyncClient):
    r = await http_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_health_lists_registered_adapters(http_client: httpx.AsyncClient):
    r = await http_client.get("/health")
    sources = r.json()["sources"]
    names = {s["name"] for s in sources}
    assert "multco_permits" in names


async def test_health_source_has_lag_after_recent_event(
    http_client: httpx.AsyncClient, fresh_test_event: str
):
    r = await http_client.get("/health")
    src = next(s for s in r.json()["sources"] if s["name"] == TEST_SOURCE_FOR_LAG)
    assert src["last_ingested_at"] is not None
    assert isinstance(src["lag_seconds"], int)
    assert src["lag_seconds"] >= 0
    assert src["lag_seconds"] < 60  # we just inserted; should be tiny
    assert src["paused"] is False
