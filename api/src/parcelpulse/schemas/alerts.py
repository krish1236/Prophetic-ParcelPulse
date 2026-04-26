from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

Axis = Literal["zoning", "flood", "permit", "ownership", "market"]
ClassifierTier = Literal["rules", "haiku", "sonnet"]


class AlertSummary(BaseModel):
    alert_id: UUID
    watchlist_id: UUID
    parcel_id: UUID
    parcel_apn: str
    triggering_event_id: UUID
    axis: Axis
    materiality_score: int
    confidence: float
    summary: str
    classifier_tier: ClassifierTier
    created_at: datetime


class AlertFeedResponse(BaseModel):
    items: list[AlertSummary]
    total: int
    limit: int
    offset: int
