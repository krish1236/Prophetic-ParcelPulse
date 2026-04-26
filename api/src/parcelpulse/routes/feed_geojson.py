"""GeoJSON FeatureCollection endpoints for the MapLibre map.

Two layers under one URL keyed by `?layer=`:
  * parcels — the watchlist's watched parcels as MultiPolygons
  * alerts  — recent alert points at each triggering parcel's centroid
"""

import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import get_session

router = APIRouter(tags=["feed"])

ALERT_LAYER_LIMIT = 500


@router.get("/feed/{watchlist_id}.geojson")
async def feed_geojson(
    watchlist_id: UUID,
    layer: Literal["parcels", "alerts"] = Query("alerts"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if layer == "parcels":
        return await _parcels_collection(session, watchlist_id)
    return await _alerts_collection(session, watchlist_id)


async def _parcels_collection(
    session: AsyncSession, watchlist_id: UUID
) -> dict[str, Any]:
    rows = await session.execute(
        text("""
            SELECT
                p.parcel_id,
                p.apn,
                ST_AsGeoJSON(p.geom) AS geom_json,
                p.attrs->>'site_address' AS site_address,
                p.attrs->>'zoning' AS zoning
            FROM parcels p
            JOIN watched_parcels wp USING (parcel_id)
            WHERE wp.watchlist_id = :w
        """),
        {"w": str(watchlist_id)},
    )
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(r["geom_json"]),
            "properties": {
                "parcel_id": str(r["parcel_id"]),
                "apn": r["apn"],
                "site_address": r["site_address"],
                "zoning": r["zoning"],
            },
        }
        for r in rows.mappings()
    ]
    return {"type": "FeatureCollection", "features": features}


async def _alerts_collection(
    session: AsyncSession, watchlist_id: UUID
) -> dict[str, Any]:
    rows = await session.execute(
        text("""
            SELECT
                a.alert_id,
                a.axis,
                a.materiality_score,
                a.confidence,
                a.summary,
                a.created_at,
                a.classifier_tier,
                ST_AsGeoJSON(p.centroid) AS geom_json,
                p.apn
            FROM alerts a
            JOIN parcels p ON p.parcel_id = a.parcel_id
            WHERE a.watchlist_id = :w
            ORDER BY a.created_at DESC
            LIMIT :lim
        """),
        {"w": str(watchlist_id), "lim": ALERT_LAYER_LIMIT},
    )
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(r["geom_json"]),
            "properties": {
                "alert_id": str(r["alert_id"]),
                "axis": r["axis"],
                "materiality_score": r["materiality_score"],
                "confidence": r["confidence"],
                "summary": r["summary"],
                "apn": r["apn"],
                "classifier_tier": r["classifier_tier"],
                "created_at": r["created_at"].isoformat(),
            },
        }
        for r in rows.mappings()
    ]
    return {"type": "FeatureCollection", "features": features}
