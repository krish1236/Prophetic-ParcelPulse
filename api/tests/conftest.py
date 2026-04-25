"""Pytest fixtures for integration tests against the local Postgres+PostGIS stack.

Tests assume `docker compose -f infra/docker-compose.yml up -d` is running and
migrations are applied (`alembic upgrade head`).
"""

from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import SessionLocal, engine
from parcelpulse.main import app


@pytest_asyncio.fixture(autouse=True)
async def _isolate_engine_pool():
    # SQLAlchemy's async pool can hold connections created in a previous test's
    # event loop; pytest-asyncio gives each test a fresh loop, so those orphaned
    # connections raise "Event loop is closed" on teardown. Dispose between tests.
    yield
    await engine.dispose()

TEST_COUNTY_FIPS = "99999"
TEST_APN = "TEST-APN-1"
TEST_APN_2 = "TEST-APN-2"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def seeded_parcels(db_session: AsyncSession) -> AsyncIterator[list[UUID]]:
    # Two test parcels in a fictitious county, well away from any real Multnomah data
    # so they don't collide with the loader-populated rows. Both are simple boxes.
    rows = await db_session.execute(
        text("""
            INSERT INTO parcels (county_fips, apn, geom, centroid)
            VALUES
                (
                    :fips, :apn1,
                    ST_Multi(ST_GeomFromText(
                        'POLYGON((-100.10 40.00, -100.10 40.10, -100.00 40.10, -100.00 40.00, -100.10 40.00))',
                        4326
                    )),
                    ST_GeomFromText('POINT(-100.05 40.05)', 4326)
                ),
                (
                    :fips, :apn2,
                    ST_Multi(ST_GeomFromText(
                        'POLYGON((-100.30 40.00, -100.30 40.10, -100.20 40.10, -100.20 40.00, -100.30 40.00))',
                        4326
                    )),
                    ST_GeomFromText('POINT(-100.25 40.05)', 4326)
                )
            RETURNING parcel_id
        """),
        {"fips": TEST_COUNTY_FIPS, "apn1": TEST_APN, "apn2": TEST_APN_2},
    )
    ids = [r[0] for r in rows.all()]
    await db_session.commit()
    try:
        yield ids
    finally:
        await db_session.execute(
            text("DELETE FROM parcels WHERE parcel_id = ANY(:ids)"),
            {"ids": ids},
        )
        await db_session.commit()
