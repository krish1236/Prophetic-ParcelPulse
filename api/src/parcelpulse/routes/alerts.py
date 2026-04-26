from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import get_session
from parcelpulse.schemas.alerts import AlertDetail

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/{alert_id}", response_model=AlertDetail)
async def get_alert(
    alert_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> AlertDetail:
    row = (
        await session.execute(
            text("""
                SELECT
                    a.alert_id, a.watchlist_id, a.parcel_id, p.apn AS parcel_apn,
                    p.attrs->>'site_address' AS parcel_address,
                    a.triggering_event_id, e.source AS event_source, e.event_type,
                    e.payload AS event_payload,
                    a.axis, a.materiality_score, a.confidence,
                    a.summary, a.decision_trace, a.classifier_tier, a.created_at
                FROM alerts a
                JOIN parcels p ON p.parcel_id = a.parcel_id
                JOIN events e ON e.event_id = a.triggering_event_id
                WHERE a.alert_id = :a
            """),
            {"a": str(alert_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return AlertDetail(**dict(row))
