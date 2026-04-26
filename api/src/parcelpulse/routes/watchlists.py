import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import get_session
from parcelpulse.rate_limit import check_and_increment
from parcelpulse.schemas.alerts import (
    AlertFeedResponse,
    AlertSummary,
    WatchedParcelsAddRequest,
    WatchedParcelsAddResponse,
    WatchlistCreateRequest,
    WatchlistDetail,
)
from parcelpulse.settings import settings

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

# UUID space for watchlists created by anonymous (visitor) flows. Real
# multi-tenant workspaces are out of scope for the demo (vision §12).
ANONYMOUS_WORKSPACE_ID = UUID("00000000-0000-0000-0000-0000ffff0000")
MAX_PARCELS_PER_RESOLVE = 200


@router.get("/{watchlist_id}/feed", response_model=AlertFeedResponse)
async def get_feed(
    watchlist_id: UUID,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    axis: str | None = Query(None, description="Filter to a single materiality axis."),
    min_score: int | None = Query(
        None, ge=0, le=100, description="Drop alerts below this materiality score."
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> AlertFeedResponse:
    clauses: list[str] = ["a.watchlist_id = :wl"]
    params: dict[str, object] = {
        "wl": str(watchlist_id),
        "limit": limit,
        "offset": offset,
    }
    if from_ts is not None:
        clauses.append("a.created_at >= :from_ts")
        params["from_ts"] = from_ts
    if to_ts is not None:
        clauses.append("a.created_at < :to_ts")
        params["to_ts"] = to_ts
    if axis is not None:
        clauses.append("a.axis = :axis")
        params["axis"] = axis
    if min_score is not None:
        clauses.append("a.materiality_score >= :min_score")
        params["min_score"] = min_score

    where = " AND ".join(clauses)

    items_sql = text(f"""
        SELECT
            a.alert_id, a.watchlist_id, a.parcel_id, p.apn AS parcel_apn,
            a.triggering_event_id, e.source AS event_source,
            a.axis, a.materiality_score, a.confidence,
            a.summary, a.classifier_tier, a.created_at
        FROM alerts a
        JOIN parcels p ON p.parcel_id = a.parcel_id
        JOIN events e ON e.event_id = a.triggering_event_id
        WHERE {where}
        ORDER BY a.created_at DESC, a.alert_id
        LIMIT :limit OFFSET :offset
    """)
    count_sql = text(f"SELECT count(*) FROM alerts a WHERE {where}")

    rows = (await session.execute(items_sql, params)).mappings().all()
    total = (await session.execute(count_sql, params)).scalar_one()

    return AlertFeedResponse(
        items=[AlertSummary(**dict(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _client_ip(request: Request) -> str:
    """Best-effort IP for rate-limit keying. Honors X-Forwarded-For if present
    (Phase 11 sets the proxy in front of Railway)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("", response_model=WatchlistDetail)
async def create_watchlist(
    req: WatchlistCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WatchlistDetail:
    ip = _client_ip(request)
    allowed, count = await check_and_increment(
        f"rl:wl_create:{ip}",
        limit=settings.watchlist_create_rate_limit,
        window_seconds=settings.watchlist_create_rate_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                f"rate limit exceeded ({count} > "
                f"{settings.watchlist_create_rate_limit} per "
                f"{settings.watchlist_create_rate_window_seconds // 60}min)"
            ),
        )
    row = (
        await session.execute(
            text("""
                INSERT INTO watchlists (workspace_id, name, deal_thesis, thesis_version)
                VALUES (:ws, :name, :thesis, 1)
                RETURNING watchlist_id, name, deal_thesis, created_at
            """),
            {
                "ws": str(ANONYMOUS_WORKSPACE_ID),
                "name": req.name,
                "thesis": req.deal_thesis,
            },
        )
    ).mappings().one()
    await session.commit()
    return WatchlistDetail(
        watchlist_id=row["watchlist_id"],
        name=row["name"],
        deal_thesis=row["deal_thesis"],
        parcel_count=0,
        alert_count=0,
        created_at=row["created_at"],
    )


@router.get("/{watchlist_id}", response_model=WatchlistDetail)
async def get_watchlist(
    watchlist_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> WatchlistDetail:
    row = (
        await session.execute(
            text("""
                SELECT
                    w.watchlist_id, w.name, w.deal_thesis, w.created_at,
                    (SELECT count(*) FROM watched_parcels WHERE watchlist_id = w.watchlist_id)
                        AS parcel_count,
                    (SELECT count(*) FROM alerts WHERE watchlist_id = w.watchlist_id)
                        AS alert_count
                FROM watchlists w
                WHERE w.watchlist_id = :id
            """),
            {"id": str(watchlist_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="watchlist not found")
    return WatchlistDetail(**dict(row))


@router.post("/{watchlist_id}/parcels", response_model=WatchedParcelsAddResponse)
async def add_parcels(
    watchlist_id: UUID,
    req: WatchedParcelsAddRequest,
    session: AsyncSession = Depends(get_session),
) -> WatchedParcelsAddResponse:
    if not req.apns and not req.polygon:
        raise HTTPException(
            status_code=400, detail="must provide either apns or polygon"
        )
    # Confirm the watchlist exists; ON CONFLICT silently no-ops on a missing FK
    # otherwise.
    exists = (
        await session.execute(
            text("SELECT 1 FROM watchlists WHERE watchlist_id = :id"),
            {"id": str(watchlist_id)},
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="watchlist not found")

    not_found = 0
    if req.apns:
        # Find APNs that match a parcel before insert so we can report misses.
        matched = (
            await session.execute(
                text(
                    "SELECT parcel_id, apn FROM parcels "
                    "WHERE apn = ANY(:apns) AND county_fips = '41051'"
                ),
                {"apns": req.apns},
            )
        ).mappings().all()
        not_found = len(req.apns) - len(matched)
        added_rows = await session.execute(
            text("""
                INSERT INTO watched_parcels (watchlist_id, parcel_id)
                SELECT :w, parcel_id FROM parcels
                WHERE apn = ANY(:apns) AND county_fips = '41051'
                ON CONFLICT (watchlist_id, parcel_id) DO NOTHING
                RETURNING parcel_id
            """),
            {"w": str(watchlist_id), "apns": req.apns},
        )
        added = len(added_rows.fetchall())
    else:
        added_rows = await session.execute(
            text(f"""
                INSERT INTO watched_parcels (watchlist_id, parcel_id)
                SELECT :w, p.parcel_id
                FROM parcels p
                WHERE p.county_fips = '41051'
                  AND ST_Intersects(
                      p.geom,
                      ST_SetSRID(ST_GeomFromGeoJSON(:poly), 4326)
                  )
                ORDER BY p.parcel_id
                LIMIT {MAX_PARCELS_PER_RESOLVE}
                ON CONFLICT (watchlist_id, parcel_id) DO NOTHING
                RETURNING parcel_id
            """),
            {"w": str(watchlist_id), "poly": json.dumps(req.polygon)},
        )
        added = len(added_rows.fetchall())

    total = (
        await session.execute(
            text(
                "SELECT count(*) FROM watched_parcels WHERE watchlist_id = :w"
            ),
            {"w": str(watchlist_id)},
        )
    ).scalar_one()
    await session.commit()
    return WatchedParcelsAddResponse(
        added=added, not_found=not_found, total_watched=total
    )
