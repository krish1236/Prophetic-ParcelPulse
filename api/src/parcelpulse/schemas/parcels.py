from uuid import UUID

from pydantic import BaseModel


class ParcelSummary(BaseModel):
    parcel_id: UUID
    county_fips: str
    apn: str
    centroid: tuple[float, float]
    bbox: tuple[float, float, float, float]
    attrs: dict


class ParcelSearchResponse(BaseModel):
    items: list[ParcelSummary]
    total: int
    limit: int
    offset: int
