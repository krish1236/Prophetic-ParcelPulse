"""Source adapter contracts.

Every external data source (Multco Permits, FEMA NFHL, zoning amendments, ...)
implements `SourceAdapter` and emits `CanonicalEvent` instances. Downstream code —
ingestion, dedupe, classification, replay — only ever sees `CanonicalEvent`,
never source-specific shapes.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class CanonicalEvent(BaseModel):
    """Source-agnostic event. Maps 1:1 to a row in the `events` table."""

    model_config = ConfigDict(extra="forbid")

    source: str
    external_id: str
    event_type: str
    payload: dict[str, Any]
    geometry: dict[str, Any] | None  # GeoJSON Geometry, EPSG:4326
    occurred_at: datetime

    def payload_hash(self) -> bytes:
        """Stable sha256 over the canonical JSON form of `payload`.

        Used as part of the events dedupe key (source, external_id, payload_hash).
        Sorting keys + tight separators makes the hash invariant under upstream
        whitespace or key-order changes.
        """
        canonical = json.dumps(
            self.payload, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(canonical.encode("utf-8")).digest()


@runtime_checkable
class SourceAdapter(Protocol):
    """Contract every source adapter must satisfy.

    Phase 2 only uses scheduled adapters; webhook-mode hooks (verify, parse) will
    be added when the first webhook source lands.
    """

    name: str
    mode: Literal["scheduled", "webhook"]
    schedule_expr: str | None  # cron expression for scheduled mode, else None

    async def fetch(self) -> list[CanonicalEvent]:
        """Pull from the source and return canonical events. Called by the scheduler."""
        ...
