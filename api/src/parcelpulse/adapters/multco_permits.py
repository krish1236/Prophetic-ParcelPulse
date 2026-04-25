"""Multco Permits adapter.

Pulls construction permits from Portland's Bureau of Development Services BDS
ArcGIS FeatureServer. Portland sits inside Multnomah County and accounts for
the bulk of permit activity, so we keep the canonical source name `multco_permits`
even though the upstream service is the City of Portland's BDS dataset.

The upstream dataset is a historical snapshot (intake dates 2007-01 through
2019-12) — fine for engine demos and Phase 7 replay determinism. The adapter
pulls the most recent PAGE_LIMIT permits each call; idempotency at the events
layer means re-runs insert zero duplicates.

Mode: scheduled, every 15 minutes.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from parcelpulse.adapters.base import CanonicalEvent

FEATURE_SERVER_URL = (
    "https://services.arcgis.com/quVN97tn06YNGj9s/arcgis/rest/services/"
    "BDS_Construction_Permit_Metric/FeatureServer/0"
)
OUT_FIELDS = (
    "FOLDER_RSN,APPROVED_TO_ISSUE_DATE,INTAKE_COMPLETE_DATE,"
    "FOLDER_TYPE,CONSTRUCTION_TYPE,WORK_TYPE,REVIEW_CLASS,PORTLAND_MAPS_URL"
)


def _classify_event_type(props: dict[str, Any]) -> str:
    work = (props.get("WORK_TYPE") or "").lower()
    if "demoli" in work:
        return "permit.demolition"
    if "new" in work:
        return "permit.new"
    if "alter" in work:
        return "permit.alteration"
    if "addition" in work:
        return "permit.addition"
    if "repair" in work:
        return "permit.repair"
    return "permit.other"


def _can_canonicalize(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") or {}
    has_id = props.get("FOLDER_RSN") is not None
    has_date = props.get("INTAKE_COMPLETE_DATE") or props.get("APPROVED_TO_ISSUE_DATE")
    return bool(has_id and has_date)


def _to_event(feature: dict[str, Any]) -> CanonicalEvent:
    props = feature["properties"]
    # Prefer the "approved to issue" date as the real-world timestamp; fall back
    # to intake if the permit hasn't been approved yet.
    ts_ms: int = props.get("APPROVED_TO_ISSUE_DATE") or props["INTAKE_COMPLETE_DATE"]
    occurred = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    return CanonicalEvent(
        source=MultcoPermitsAdapter.name,
        external_id=str(props["FOLDER_RSN"]),
        event_type=_classify_event_type(props),
        payload=props,
        geometry=feature.get("geometry"),
        occurred_at=occurred,
    )


class MultcoPermitsAdapter:
    name: ClassVar[str] = "multco_permits"
    mode: ClassVar[Literal["scheduled"]] = "scheduled"
    schedule_expr: ClassVar[str] = "*/15 * * * *"

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
                "where": "1=1",
                "outFields": OUT_FIELDS,
                "outSR": "4326",
                "f": "geojson",
                "orderByFields": "INTAKE_COMPLETE_DATE DESC",
                "resultRecordCount": str(self.PAGE_LIMIT),
            },
        )
        r.raise_for_status()
        return r.json()
