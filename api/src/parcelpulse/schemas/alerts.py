from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

Axis = Literal["zoning", "flood", "permit", "ownership", "market"]
ClassifierTier = Literal["rules", "haiku", "sonnet"]


class AlertSummary(BaseModel):
    alert_id: UUID
    watchlist_id: UUID
    parcel_id: UUID
    parcel_apn: str
    triggering_event_id: UUID
    event_source: str
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


class AlertDetail(BaseModel):
    alert_id: UUID
    watchlist_id: UUID
    parcel_id: UUID
    parcel_apn: str
    parcel_address: str | None = None
    triggering_event_id: UUID
    event_source: str
    event_type: str
    event_payload: dict
    axis: Axis
    materiality_score: int
    confidence: float
    summary: str
    decision_trace: dict
    classifier_tier: ClassifierTier
    created_at: datetime


class WatchlistCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    deal_thesis: str = Field(min_length=20, max_length=2000)


class WatchlistDetail(BaseModel):
    watchlist_id: UUID
    name: str
    deal_thesis: str
    parcel_count: int
    alert_count: int
    created_at: datetime


class WatchedParcelsAddRequest(BaseModel):
    apns: list[str] | None = None
    polygon: dict[str, Any] | None = None


class WatchedParcelsAddResponse(BaseModel):
    added: int
    not_found: int
    total_watched: int
