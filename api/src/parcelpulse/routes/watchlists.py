from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import get_session
from parcelpulse.schemas.alerts import AlertFeedResponse, AlertSummary

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


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
            a.triggering_event_id, a.axis, a.materiality_score, a.confidence,
            a.summary, a.classifier_tier, a.created_at
        FROM alerts a
        JOIN parcels p ON p.parcel_id = a.parcel_id
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
