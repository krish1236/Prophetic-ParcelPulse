"""Fixture adapter for listing + comp events.

Real listing/comp data is paywalled (RMLS, CoStar). This adapter emits a
small hand-curated set so the engine + UI can show the listings axis
end-to-end. Source name `fixture_listings` triggers the fixture badge on
resulting alerts.
"""

from pathlib import Path
from typing import ClassVar, Literal

from parcelpulse.adapters._fixture import load_fixture_events
from parcelpulse.adapters.base import CanonicalEvent

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "listings_events.json"


class FixtureListingsAdapter:
    name: ClassVar[str] = "fixture_listings"
    mode: ClassVar[Literal["scheduled"]] = "scheduled"
    schedule_expr: ClassVar[str] = "0 8 * * *"

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._fixture_path = fixture_path or FIXTURE_PATH

    async def fetch(self) -> list[CanonicalEvent]:
        return load_fixture_events(
            source=self.name, fixture_path=self._fixture_path
        )
