"""FEMA NFHL adapter — Letters of Map Revision (LOMR) for Multnomah County.

LOMRs are the "what changed" feed for FEMA's National Flood Hazard Layer:
each one revises a portion of a flood map for a community. The county is
identified by `DFIRM_ID='41051C'` (Oregon FIPS 41 + Multnomah 051), so we
filter at the source rather than clipping a bbox client-side. This keeps
the payload small (Multnomah typically has < 50 LOMRs ever) and avoids
pulling the entire national NFHL.

Mode: scheduled, weekly. Idempotency at the events layer means the same
LOMR_ID re-pulled each week inserts zero duplicates.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from parcelpulse.adapters.base import CanonicalEvent

FEATURE_SERVER_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/1"
)
DFIRM_ID_MULTNOMAH = "41051C"
OUT_FIELDS = "LOMR_ID,EFF_DATE,CASE_NO,STATUS,DFIRM_ID,SCALE"


def _can_canonicalize(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") or {}
    return bool(props.get("LOMR_ID")) and props.get("EFF_DATE") is not None


def _to_event(feature: dict[str, Any]) -> CanonicalEvent:
    props = feature["properties"]
    occurred = datetime.fromtimestamp(props["EFF_DATE"] / 1000, tz=UTC)
    return CanonicalEvent(
        source=FemaNfhlAdapter.name,
        external_id=str(props["LOMR_ID"]),
        event_type="flood.lomr",
        payload=props,
        geometry=feature.get("geometry"),
        occurred_at=occurred,
    )


class FemaNfhlAdapter:
    name: ClassVar[str] = "fema_nfhl"
    mode: ClassVar[Literal["scheduled"]] = "scheduled"
    # Weekly. NFHL is officially updated monthly; weekly catches new LOMRs
    # within ~7 days of issuance without burning the upstream service.
    schedule_expr: ClassVar[str] = "0 7 * * 1"

    PAGE_LIMIT: ClassVar[int] = 100

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client

    async def fetch(self) -> list[CanonicalEvent]:
        client = self._http or httpx.AsyncClient(timeout=60.0)
        owns_client = self._http is None
        try:
            response = await self._query(client)
            features = response.get("features", [])
            return [_to_event(f) for f in features if _can_canonicalize(f)]
        finally:
            if owns_client:
                await client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def _query(self, client: httpx.AsyncClient) -> dict[str, Any]:
        r = await client.get(
            f"{FEATURE_SERVER_URL}/query",
            params={
                "where": f"DFIRM_ID='{DFIRM_ID_MULTNOMAH}'",
                "outFields": OUT_FIELDS,
                "outSR": "4326",
                "f": "geojson",
                "orderByFields": "EFF_DATE DESC",
                "resultRecordCount": str(self.PAGE_LIMIT),
            },
        )
        r.raise_for_status()
        return r.json()
