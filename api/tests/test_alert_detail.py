"""Integration tests for GET /alerts/{alert_id}."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-0000eeee0001")
TEST_FIPS = "99995"
PARCEL_WKT = (
    "POLYGON((-100.0005 39.9995, -100.0005 40.0005, "
    "-99.9995 40.0005, -99.9995 39.9995, -100.0005 39.9995))"
)


@pytest_asyncio.fixture
async def alert_world(db_session: AsyncSession):
    parcel_id = (
        await db_session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid, attrs) "
                f"VALUES (:f, :apn, ST_Multi(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                f"ST_Centroid(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                "'{\"site_address\":\"123 DETAIL ST\"}'::jsonb"
                ") RETURNING parcel_id"
            ),
            {"f": TEST_FIPS, "apn": "DETAIL-TEST"},
        )
    ).scalar_one()
    wl_id = (
        await db_session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis) "
                "VALUES (:ws, 'detail test', 'test') RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    import json as _json
    event_id = (
        await db_session.execute(
            text(
                "INSERT INTO events (source, external_id, payload_hash, event_type, "
                "payload, occurred_at) VALUES ('detail_test', :eid, :h, 'permit.new', "
                "CAST(:payload AS jsonb), :occ) RETURNING event_id"
            ),
            {
                "eid": str(uuid4()),
                "h": uuid4().bytes,
                "payload": _json.dumps({"WORK_TYPE": "New Construction", "FOLDER_RSN": 42}),
                "occ": datetime.now(UTC),
            },
        )
    ).scalar_one()
    alert_id = (
        await db_session.execute(
            text(
                "INSERT INTO alerts (watchlist_id, parcel_id, triggering_event_id, "
                "axis, materiality_score, confidence, summary, decision_trace, "
                "classifier_tier, dedupe_key) "
                "VALUES (:w, :p, :e, 'permit', 75, 0.85, 'Material change detected.', "
                "'{\"placeholder\": true, \"fixture\": false}'::jsonb, 'haiku', :dk) "
                "RETURNING alert_id"
            ),
            {
                "w": str(wl_id),
                "p": str(parcel_id),
                "e": str(event_id),
                "dk": "alert-detail-test",
            },
        )
    ).scalar_one()
    await db_session.commit()
    yield {"alert_id": alert_id, "wl_id": wl_id, "parcel_id": parcel_id, "event_id": event_id}

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
    await db_session.execute(text("DELETE FROM events WHERE source = 'detail_test'"))
    await db_session.commit()


async def test_alert_detail_returns_404_for_unknown(http_client: httpx.AsyncClient):
    r = await http_client.get(f"/alerts/{uuid4()}")
    assert r.status_code == 404


async def test_alert_detail_returns_full_payload(
    http_client: httpx.AsyncClient, alert_world
):
    r = await http_client.get(f"/alerts/{alert_world['alert_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["alert_id"] == str(alert_world["alert_id"])
    assert body["parcel_apn"] == "DETAIL-TEST"
    assert body["parcel_address"] == "123 DETAIL ST"
    assert body["event_source"] == "detail_test"
    assert body["event_type"] == "permit.new"
    assert body["event_payload"]["FOLDER_RSN"] == 42
    assert body["axis"] == "permit"
    assert body["materiality_score"] == 75
    assert body["decision_trace"]["placeholder"] is True
    assert body["classifier_tier"] == "haiku"
