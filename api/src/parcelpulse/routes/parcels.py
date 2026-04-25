from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import get_session
from parcelpulse.schemas.parcels import ParcelSearchResponse, ParcelSummary

router = APIRouter(prefix="/parcels", tags=["parcels"])


@router.get("/search", response_model=ParcelSearchResponse)
async def search_parcels(
    apn: str | None = Query(None, description="Exact APN match (e.g. '1N1E14AA01200')."),
    bbox: str | None = Query(
        None,
        description="minx,miny,maxx,maxy in lon/lat (EPSG:4326). Capped at 1 degree.",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ParcelSearchResponse:
    if apn is None and bbox is None:
        raise HTTPException(status_code=400, detail="must provide either apn or bbox")

    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit, "offset": offset}

    if apn is not None:
        clauses.append("apn = :apn")
        params["apn"] = apn

    if bbox is not None:
        parts = bbox.split(",")
        if len(parts) != 4:
            raise HTTPException(status_code=400, detail="bbox must be 'minx,miny,maxx,maxy'")
        try:
            minx, miny, maxx, maxy = (float(x) for x in parts)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="bbox values must be numeric"
            ) from exc
        if maxx <= minx or maxy <= miny:
            raise HTTPException(status_code=400, detail="bbox max must exceed min")
        if (maxx - minx) > 1.0 or (maxy - miny) > 1.0:
            raise HTTPException(
                status_code=400, detail="bbox too large (>1 degree); refine your query"
            )
        params.update({"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy})
        clauses.append(
            "ST_Intersects(geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
        )

    where = " AND ".join(clauses)

    items_sql = text(f"""
        SELECT
            parcel_id,
            county_fips,
            apn,
            ST_X(centroid) AS lon,
            ST_Y(centroid) AS lat,
            ST_XMin(geom) AS minx,
            ST_YMin(geom) AS miny,
            ST_XMax(geom) AS maxx,
            ST_YMax(geom) AS maxy,
            attrs
        FROM parcels
        WHERE {where}
        ORDER BY parcel_id
        LIMIT :limit OFFSET :offset
    """)
    count_sql = text(f"SELECT count(*) FROM parcels WHERE {where}")

    rows = (await session.execute(items_sql, params)).mappings().all()
    total = (await session.execute(count_sql, params)).scalar_one()

    items = [
        ParcelSummary(
            parcel_id=r["parcel_id"],
            county_fips=r["county_fips"],
            apn=r["apn"],
            centroid=(r["lon"], r["lat"]),
            bbox=(r["minx"], r["miny"], r["maxx"], r["maxy"]),
            attrs=r["attrs"] or {},
        )
        for r in rows
    ]
    return ParcelSearchResponse(items=items, total=total, limit=limit, offset=offset)
