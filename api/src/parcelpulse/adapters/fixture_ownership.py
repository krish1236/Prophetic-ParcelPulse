"""Fixture adapter for Multnomah deeds + LLC filings.

Real public deed data lives in the Multnomah Survey & Assessment Image
Locator (SAIL) — no clean public API. Until that ingestion is built, this
adapter emits hand-curated events plausible enough to demo the ownership
axis end-to-end.
"""

from pathlib import Path
from typing import ClassVar, Literal

from parcelpulse.adapters._fixture import load_fixture_events
from parcelpulse.adapters.base import CanonicalEvent

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "ownership_events.json"


class FixtureOwnershipAdapter:
    name: ClassVar[str] = "fixture_ownership"
    mode: ClassVar[Literal["scheduled"]] = "scheduled"
    schedule_expr: ClassVar[str] = "0 7 * * *"

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._fixture_path = fixture_path or FIXTURE_PATH

    async def fetch(self) -> list[CanonicalEvent]:
        return load_fixture_events(
            source=self.name, fixture_path=self._fixture_path
        )
