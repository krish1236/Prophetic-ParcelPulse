"""Tests for GET /feed/{watchlist_id}.geojson?layer=parcels|alerts."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-00006666aaaa")
TEST_FIPS = "99993"
PARCEL_WKT = (
    "POLYGON((-100.0005 39.9995, -100.0005 40.0005, "
    "-99.9995 40.0005, -99.9995 39.9995, -100.0005 39.9995))"
)


@pytest_asyncio.fixture
async def map_world(db_session: AsyncSession):
    parcel_id = (
        await db_session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid, attrs) "
                f"VALUES (:f, :apn, ST_Multi(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                f"ST_Centroid(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                "'{\"site_address\":\"123 MAP ST\",\"zoning\":\"R5\"}'::jsonb"
                ") RETURNING parcel_id"
            ),
            {"f": TEST_FIPS, "apn": "MAP-TEST"},
        )
    ).scalar_one()
    wl_id = (
        await db_session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis) "
                "VALUES (:ws, 'map test', 'test') RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    await db_session.execute(
        text("INSERT INTO watched_parcels (watchlist_id, parcel_id) VALUES (:w, :p)"),
        {"w": str(wl_id), "p": str(parcel_id)},
    )
    event_id = (
        await db_session.execute(
            text(
                "INSERT INTO events (source, external_id, payload_hash, event_type, "
                "payload, occurred_at) VALUES ('map_test', :eid, :h, 'permit.new', "
                "'{}'::jsonb, :occ) RETURNING event_id"
            ),
            {"eid": str(uuid4()), "h": uuid4().bytes, "occ": datetime.now(UTC)},
        )
    ).scalar_one()
    alert_id = (
        await db_session.execute(
            text(
                "INSERT INTO alerts (watchlist_id, parcel_id, triggering_event_id, "
                "axis, materiality_score, confidence, summary, decision_trace, "
                "classifier_tier, dedupe_key) "
                "VALUES (:w, :p, :e, 'permit', 70, 0.85, 'Map test alert.', "
                "'{}'::jsonb, 'haiku', :dk) RETURNING alert_id"
            ),
            {
                "w": str(wl_id),
                "p": str(parcel_id),
                "e": str(event_id),
                "dk": "map-test-alert",
            },
        )
    ).scalar_one()
    await db_session.commit()
    yield {"wl_id": wl_id, "parcel_id": parcel_id, "alert_id": alert_id}

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
    await db_session.execute(text("DELETE FROM events WHERE source = 'map_test'"))
    await db_session.commit()


async def test_geojson_parcels_layer_returns_feature_collection(
    http_client: httpx.AsyncClient, map_world
):
    r = await http_client.get(
        f"/feed/{map_world['wl_id']}.geojson", params={"layer": "parcels"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    feat = body["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] in ("MultiPolygon", "Polygon")
    assert feat["properties"]["apn"] == "MAP-TEST"
    assert feat["properties"]["zoning"] == "R5"
    assert feat["properties"]["site_address"] == "123 MAP ST"


async def test_geojson_alerts_layer_returns_points_with_props(
    http_client: httpx.AsyncClient, map_world
):
    r = await http_client.get(
        f"/feed/{map_world['wl_id']}.geojson", params={"layer": "alerts"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    feat = body["features"][0]
    assert feat["geometry"]["type"] == "Point"
    coords = feat["geometry"]["coordinates"]
    assert -100.001 < coords[0] < -99.999
    assert 39.999 < coords[1] < 40.001
    props = feat["properties"]
    assert props["alert_id"] == str(map_world["alert_id"])
    assert props["axis"] == "permit"
    assert props["materiality_score"] == 70
    assert props["apn"] == "MAP-TEST"
    assert props["classifier_tier"] == "haiku"


async def test_geojson_default_layer_is_alerts(http_client: httpx.AsyncClient, map_world):
    r = await http_client.get(f"/feed/{map_world['wl_id']}.geojson")
    assert r.status_code == 200
    feat = r.json()["features"][0]
    assert feat["geometry"]["type"] == "Point"


async def test_geojson_unknown_watchlist_returns_empty_collection(
    http_client: httpx.AsyncClient,
):
    r = await http_client.get(f"/feed/{uuid4()}.geojson", params={"layer": "alerts"})
    assert r.status_code == 200
    assert r.json() == {"type": "FeatureCollection", "features": []}


async def test_geojson_invalid_layer_returns_422(
    http_client: httpx.AsyncClient, map_world
):
    r = await http_client.get(
        f"/feed/{map_world['wl_id']}.geojson", params={"layer": "bogus"}
    )
    assert r.status_code == 422
