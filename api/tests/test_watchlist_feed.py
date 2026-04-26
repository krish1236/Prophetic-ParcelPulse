"""Integration tests for GET /watchlists/{id}/feed."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-0000dddd0001")
TEST_FIPS = "99996"
PARCEL_WKT = (
    "POLYGON((-100.0005 39.9995, -100.0005 40.0005, "
    "-99.9995 40.0005, -99.9995 39.9995, -100.0005 39.9995))"
)


async def _make_alert(
    session: AsyncSession,
    *,
    wl_id: UUID,
    parcel_id: UUID,
    event_id: UUID,
    axis: str,
    score: int,
    created_at: datetime | None = None,
) -> UUID:
    created = created_at or datetime.now(UTC)
    aid = (
        await session.execute(
            text(
                "INSERT INTO alerts (watchlist_id, parcel_id, triggering_event_id, "
                "axis, materiality_score, confidence, summary, decision_trace, "
                "classifier_tier, dedupe_key, created_at) "
                "VALUES (:w, :p, :e, :ax, :s, 0.8, 'test summary', "
                "'{}'::jsonb, 'haiku', :dk, :ts) RETURNING alert_id"
            ),
            {
                "w": str(wl_id),
                "p": str(parcel_id),
                "e": str(event_id),
                "ax": axis,
                "s": score,
                "dk": f"feed-test-{uuid4()}",
                "ts": created,
            },
        )
    ).scalar_one()
    await session.commit()
    return aid


@pytest_asyncio.fixture
async def feed_world(db_session: AsyncSession):
    parcel_id = (
        await db_session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid) "
                f"VALUES (:f, :apn, ST_Multi(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                f"ST_Centroid(ST_GeomFromText('{PARCEL_WKT}', 4326))) RETURNING parcel_id"
            ),
            {"f": TEST_FIPS, "apn": "FEED-TEST"},
        )
    ).scalar_one()
    wl_id = (
        await db_session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis) "
                "VALUES (:ws, 'feed test', 'test') RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    event_id = (
        await db_session.execute(
            text(
                "INSERT INTO events (source, external_id, payload_hash, event_type, "
                "payload, occurred_at) VALUES ('feed_test', :eid, :h, 'permit.new', "
                "'{}'::jsonb, now()) RETURNING event_id"
            ),
            {"eid": str(uuid4()), "h": uuid4().bytes},
        )
    ).scalar_one()
    await db_session.commit()
    yield {"wl_id": wl_id, "parcel_id": parcel_id, "event_id": event_id}
    await db_session.execute(
        text(
            "DELETE FROM alerts WHERE watchlist_id IN "
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
    await db_session.execute(text("DELETE FROM events WHERE source = 'feed_test'"))
    await db_session.commit()


async def test_feed_returns_empty_for_unknown_watchlist(http_client: httpx.AsyncClient):
    r = await http_client.get(f"/watchlists/{uuid4()}/feed")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_feed_returns_alerts_in_descending_order(
    http_client: httpx.AsyncClient, feed_world, db_session: AsyncSession
):
    now = datetime.now(UTC)
    a1 = await _make_alert(
        db_session, **feed_world, axis="permit", score=70,
        created_at=now - timedelta(hours=2),
    )
    a2 = await _make_alert(
        db_session, **feed_world, axis="permit", score=50, created_at=now,
    )
    r = await http_client.get(f"/watchlists/{feed_world['wl_id']}/feed")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    ids = [item["alert_id"] for item in body["items"]]
    assert ids == [str(a2), str(a1)]
    assert body["items"][0]["parcel_apn"] == "FEED-TEST"


async def test_feed_filters_by_axis(
    http_client: httpx.AsyncClient, feed_world, db_session: AsyncSession
):
    await _make_alert(db_session, **feed_world, axis="permit", score=70)
    await _make_alert(db_session, **feed_world, axis="flood", score=70)
    r = await http_client.get(f"/watchlists/{feed_world['wl_id']}/feed?axis=flood")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["axis"] == "flood"


async def test_feed_filters_by_min_score(
    http_client: httpx.AsyncClient, feed_world, db_session: AsyncSession
):
    await _make_alert(db_session, **feed_world, axis="permit", score=20)
    await _make_alert(db_session, **feed_world, axis="permit", score=80)
    r = await http_client.get(
        f"/watchlists/{feed_world['wl_id']}/feed?min_score=50"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["materiality_score"] == 80


async def test_feed_filters_by_time_range(
    http_client: httpx.AsyncClient, feed_world, db_session: AsyncSession
):
    now = datetime.now(UTC)
    await _make_alert(db_session, **feed_world, axis="permit", score=50,
                      created_at=now - timedelta(days=10))
    inside = await _make_alert(
        db_session, **feed_world, axis="permit", score=50,
        created_at=now - timedelta(days=2),
    )
    r = await http_client.get(
        f"/watchlists/{feed_world['wl_id']}/feed",
        params={
            "from": (now - timedelta(days=5)).isoformat(),
            "to": now.isoformat(),
        },
    )
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["alert_id"] == str(inside)


async def test_feed_pagination(
    http_client: httpx.AsyncClient, feed_world, db_session: AsyncSession
):
    for _ in range(3):
        await _make_alert(db_session, **feed_world, axis="permit", score=50)
    r = await http_client.get(
        f"/watchlists/{feed_world['wl_id']}/feed?limit=1&offset=1"
    )
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert body["limit"] == 1
    assert body["offset"] == 1
