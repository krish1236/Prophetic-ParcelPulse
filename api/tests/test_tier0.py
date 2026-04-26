"""Integration tests for Tier 0 spatial-join filter.

Each test seeds a watchlist + one watched parcel with a known polygon, then
inserts a synthetic event and asserts whether Tier 0 keeps or drops it.
"""

from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.materiality.tier0 import Candidate, find_candidates

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-0000aaaa0001")
TEST_FIPS = "99999"


async def _make_watchlist_with_parcel(
    session: AsyncSession, *, parcel_apn: str, parcel_polygon_wkt: str
) -> tuple[UUID, UUID]:
    parcel_id = (
        await session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid) "
                "VALUES (:fips, :apn, "
                "ST_Multi(ST_GeomFromText(:poly, 4326)), "
                "ST_Centroid(ST_GeomFromText(:poly, 4326))) RETURNING parcel_id"
            ),
            {"fips": TEST_FIPS, "apn": parcel_apn, "poly": parcel_polygon_wkt},
        )
    ).scalar_one()
    watchlist_id = (
        await session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis) "
                "VALUES (:ws, 'tier0 test', 'test thesis') RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO watched_parcels (watchlist_id, parcel_id) "
            "VALUES (:wl, :pid)"
        ),
        {"wl": str(watchlist_id), "pid": str(parcel_id)},
    )
    await session.commit()
    return watchlist_id, parcel_id


async def _insert_event(
    session: AsyncSession,
    *,
    event_type: str,
    point_wkt: str | None = None,
) -> UUID:
    geom_clause = "ST_GeomFromText(:point, 4326)" if point_wkt else "NULL"
    eid = (
        await session.execute(
            text(
                "INSERT INTO events (source, external_id, payload_hash, "
                f"event_type, payload, geometry, occurred_at) "
                f"VALUES (:s, :eid, :h, :t, '{{}}'::jsonb, {geom_clause}, now()) "
                "RETURNING event_id"
            ),
            {
                "s": "test_source",
                "eid": str(uuid4()),
                "h": uuid4().bytes,
                "t": event_type,
                "point": point_wkt,
            },
        )
    ).scalar_one()
    await session.commit()
    return eid


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db_session: AsyncSession):
    yield
    await db_session.execute(
        text("DELETE FROM watched_parcels WHERE watchlist_id IN "
             "(SELECT watchlist_id FROM watchlists WHERE workspace_id = :ws)"),
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
    await db_session.commit()


# A 0.001 deg square (~110m on a side) centered roughly at -100, 40.
PARCEL_WKT = "POLYGON((-100.0005 39.9995, -100.0005 40.0005, -99.9995 40.0005, -99.9995 39.9995, -100.0005 39.9995))"


async def test_returns_candidate_for_event_inside_watched_parcel(
    db_session: AsyncSession,
):
    wl, pid = await _make_watchlist_with_parcel(
        db_session, parcel_apn="T-INSIDE", parcel_polygon_wkt=PARCEL_WKT
    )
    eid = await _insert_event(
        db_session, event_type="permit.new", point_wkt="POINT(-100.0 40.0)"
    )
    candidates = await find_candidates(eid, db_session)
    assert candidates == [Candidate(event_id=eid, watchlist_id=wl, parcel_id=pid)]


async def test_drops_event_with_no_geometry(db_session: AsyncSession):
    await _make_watchlist_with_parcel(
        db_session, parcel_apn="T-NOGEOM", parcel_polygon_wkt=PARCEL_WKT
    )
    eid = await _insert_event(db_session, event_type="permit.new", point_wkt=None)
    assert await find_candidates(eid, db_session) == []


async def test_drops_event_with_non_material_type(db_session: AsyncSession):
    await _make_watchlist_with_parcel(
        db_session, parcel_apn="T-NONMAT", parcel_polygon_wkt=PARCEL_WKT
    )
    eid = await _insert_event(
        db_session,
        event_type="some.unknown.type",
        point_wkt="POINT(-100.0 40.0)",
    )
    assert await find_candidates(eid, db_session) == []


async def test_drops_event_outside_proximity(db_session: AsyncSession):
    await _make_watchlist_with_parcel(
        db_session, parcel_apn="T-FAR", parcel_polygon_wkt=PARCEL_WKT
    )
    # Point ~5 km north of the parcel — well outside default 500ft (152m).
    eid = await _insert_event(
        db_session, event_type="permit.new", point_wkt="POINT(-100.0 40.05)"
    )
    assert await find_candidates(eid, db_session) == []


async def test_returns_one_candidate_per_watchlist_for_same_parcel(
    db_session: AsyncSession,
):
    # Same parcel watched by two different watchlists → two candidates.
    wl1, pid = await _make_watchlist_with_parcel(
        db_session, parcel_apn="T-SHARED", parcel_polygon_wkt=PARCEL_WKT
    )
    wl2 = (
        await db_session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis) "
                "VALUES (:ws, 'tier0 test 2', 'test') RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO watched_parcels (watchlist_id, parcel_id) "
            "VALUES (:wl, :pid)"
        ),
        {"wl": str(wl2), "pid": str(pid)},
    )
    await db_session.commit()
    eid = await _insert_event(
        db_session, event_type="permit.new", point_wkt="POINT(-100.0 40.0)"
    )
    candidates = await find_candidates(eid, db_session)
    assert {c.watchlist_id for c in candidates} == {wl1, wl2}
    assert all(c.parcel_id == pid for c in candidates)
