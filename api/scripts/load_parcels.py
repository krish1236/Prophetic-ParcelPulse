"""Bootstrap loader for Multnomah County taxlot parcels.

Pulls the full taxlot dataset from the Multnomah County ArcGIS FeatureServer and
upserts into the local parcels table. Idempotent on (county_fips, apn) so re-runs
either fill new parcels or update existing ones.

Usage:
    python api/scripts/load_parcels.py [--limit N] [--page-size N]
"""

import argparse
import asyncio
import json
import sys
from typing import Any

import httpx
from sqlalchemy import text

from parcelpulse.db import SessionLocal

MULTNOMAH_FIPS = "41051"
FEATURE_SERVER_URL = (
    "https://services5.arcgis.com/x7DNZL1YqNQVNykA/arcgis/rest/services/"
    "Multnomah_County_Taxlot_Parcels/FeatureServer/0"
)
OUT_FIELDS = (
    "MAPTAXLOT,PROPID,NAME,SITUSADDR,SITUSCITY,ZONING,PROPCLASS,"
    "SIZEACRES,SIZESQFT,ACTYEARBUILT,SALE_PRICE,SALE_DATE,AssessorMap,TownshipRange"
)

UPSERT_SQL = text("""
    INSERT INTO parcels (county_fips, apn, geom, centroid, attrs)
    SELECT
        :county_fips,
        row.apn,
        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(row.geom), 4326)),
        ST_Centroid(ST_SetSRID(ST_GeomFromGeoJSON(row.geom), 4326)),
        row.attrs
    FROM jsonb_to_recordset(CAST(:rows AS jsonb))
        AS row(apn TEXT, geom TEXT, attrs JSONB)
    WHERE row.apn IS NOT NULL AND row.apn <> ''
    ON CONFLICT (county_fips, apn) DO UPDATE SET
        geom = EXCLUDED.geom,
        centroid = EXCLUDED.centroid,
        attrs = EXCLUDED.attrs,
        last_projected_at = NOW()
""")


async def fetch_count(client: httpx.AsyncClient) -> int:
    r = await client.get(
        f"{FEATURE_SERVER_URL}/query",
        params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
    )
    r.raise_for_status()
    return int(r.json()["count"])


async def fetch_page(
    client: httpx.AsyncClient, offset: int, page_size: int
) -> list[dict[str, Any]]:
    r = await client.get(
        f"{FEATURE_SERVER_URL}/query",
        params={
            "where": "1=1",
            "outFields": OUT_FIELDS,
            "outSR": "4326",
            "f": "geojson",
            "orderByFields": "OBJECTID_1",
            "resultOffset": str(offset),
            "resultRecordCount": str(page_size),
        },
    )
    r.raise_for_status()
    return r.json().get("features", [])


def feature_to_row(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = feature.get("properties") or {}
    geom = feature.get("geometry")
    apn = (props.get("MAPTAXLOT") or "").strip()
    if not apn or not geom:
        return None
    attrs = {
        "propid": props.get("PROPID"),
        "owner_name": props.get("NAME"),
        "site_address": props.get("SITUSADDR"),
        "city": props.get("SITUSCITY"),
        "zoning": props.get("ZONING"),
        "prop_class": props.get("PROPCLASS"),
        "area_acres": props.get("SIZEACRES"),
        "area_sqft": props.get("SIZESQFT"),
        "year_built": props.get("ACTYEARBUILT"),
        "sale_price": props.get("SALE_PRICE"),
        "sale_date_ms": props.get("SALE_DATE"),
        "assessor_map": props.get("AssessorMap"),
        "township_range": props.get("TownshipRange"),
    }
    attrs = {k: v for k, v in attrs.items() if v is not None}
    return {"apn": apn, "geom": json.dumps(geom), "attrs": attrs}


async def upsert_batch(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    # Multnomah taxlot data occasionally repeats the same MAPTAXLOT within a page
    # (multiple records sharing one APN — usually condo units on a parent lot).
    # ON CONFLICT DO UPDATE rejects duplicate keys in a single statement, so
    # dedupe per-batch and keep the last occurrence.
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped[row["apn"]] = row
    payload = list(deduped.values())
    async with SessionLocal() as session:
        await session.execute(
            UPSERT_SQL,
            {"county_fips": MULTNOMAH_FIPS, "rows": json.dumps(payload)},
        )
        await session.commit()


async def run(limit: int | None, page_size: int) -> None:
    async with httpx.AsyncClient(timeout=120.0) as client:
        total = await fetch_count(client)
        target = min(total, limit) if limit else total
        print(
            f"loading {target:,} of {total:,} multnomah parcels (page_size={page_size})",
            flush=True,
        )

        offset = 0
        loaded = 0
        while loaded < target:
            features = await fetch_page(client, offset, page_size)
            if not features:
                break
            rows = [r for r in (feature_to_row(f) for f in features) if r]
            await upsert_batch(rows)
            loaded += len(features)
            offset += len(features)
            print(f"  loaded {loaded:,}/{target:,}", flush=True)
            if limit and loaded >= limit:
                break
        print(f"done: upserted approximately {loaded:,} parcels", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Load Multnomah taxlot parcels into the local DB."
    )
    ap.add_argument(
        "--limit", type=int, default=None, help="Cap loaded parcels (for dev iteration)."
    )
    ap.add_argument(
        "--page-size",
        type=int,
        default=2000,
        help="ArcGIS resultRecordCount per request (max 2000).",
    )
    args = ap.parse_args()
    asyncio.run(run(limit=args.limit, page_size=args.page_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
