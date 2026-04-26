"""Shared loader for fixture adapters.

Fixture JSON shape:
    [
      {
        "external_id": "string",      # stable id for idempotent ingest
        "event_type": "string",       # must be in tier0.MATERIAL_EVENT_TYPES
        "occurred_offset_days": int,  # event "happened" N days before now
        "geometry": {GeoJSON} | null,
        "payload": {anything}
      },
      ...
    ]
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from parcelpulse.adapters.base import CanonicalEvent


def load_fixture_events(*, source: str, fixture_path: Path) -> list[CanonicalEvent]:
    records: list[dict[str, Any]] = json.loads(fixture_path.read_text())
    now = datetime.now(UTC)
    return [
        CanonicalEvent(
            source=source,
            external_id=r["external_id"],
            event_type=r["event_type"],
            payload=r["payload"],
            geometry=r.get("geometry"),
            occurred_at=now - timedelta(days=r.get("occurred_offset_days", 0)),
        )
        for r in records
    ]
