"""Fixture adapter for Multnomah / Portland zoning amendments.

Real Portland zoning amendments don't ship through a clean public API — they
land in council ordinances and PDF PDFs scraped manually. Until that
ingestion is built (out of scope for the demo), this adapter emits a small
hand-curated set of plausible amendment events so the engine + UI can show
the zoning axis end-to-end.

Source name `fixture_zoning` is detected by the UI to render a "fixture data"
badge on resulting alerts — the demo never claims fixture content is real.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Literal

from parcelpulse.adapters.base import CanonicalEvent

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "zoning_events.json"


class FixtureZoningAdapter:
    name: ClassVar[str] = "fixture_zoning"
    mode: ClassVar[Literal["scheduled"]] = "scheduled"
    schedule_expr: ClassVar[str] = "0 6 * * *"

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._fixture_path = fixture_path or FIXTURE_PATH

    async def fetch(self) -> list[CanonicalEvent]:
        records: list[dict[str, Any]] = json.loads(self._fixture_path.read_text())
        now = datetime.now(UTC)
        events: list[CanonicalEvent] = []
        for r in records:
            occurred = now - timedelta(days=r.get("occurred_offset_days", 0))
            events.append(
                CanonicalEvent(
                    source=self.name,
                    external_id=r["external_id"],
                    event_type=r["event_type"],
                    payload=r["payload"],
                    geometry=r.get("geometry"),
                    occurred_at=occurred,
                )
            )
        return events
