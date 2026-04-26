from datetime import UTC, datetime

from parcelpulse.adapters.base import CanonicalEvent
from parcelpulse.adapters.fixture_zoning import FixtureZoningAdapter


async def test_fetch_returns_canonical_events_with_fixture_source():
    adapter = FixtureZoningAdapter()
    events = await adapter.fetch()
    assert len(events) >= 1
    assert all(isinstance(e, CanonicalEvent) for e in events)
    assert all(e.source == "fixture_zoning" for e in events)


async def test_fetch_event_types_are_zoning():
    adapter = FixtureZoningAdapter()
    events = await adapter.fetch()
    for e in events:
        assert e.event_type.startswith("zoning.")


async def test_fetch_external_ids_are_unique():
    adapter = FixtureZoningAdapter()
    events = await adapter.fetch()
    assert len({e.external_id for e in events}) == len(events)


async def test_fetch_occurred_at_is_recent():
    adapter = FixtureZoningAdapter()
    events = await adapter.fetch()
    now = datetime.now(UTC)
    for e in events:
        # All fixture events are within the last year by design.
        delta_days = (now - e.occurred_at).days
        assert 0 <= delta_days <= 365


async def test_fetch_carries_geometry_when_present():
    adapter = FixtureZoningAdapter()
    events = await adapter.fetch()
    geoms = [e.geometry for e in events if e.geometry is not None]
    assert len(geoms) >= 1
    for g in geoms:
        assert g["type"] == "Point"
        assert len(g["coordinates"]) == 2


async def test_idempotent_external_ids_across_runs():
    adapter = FixtureZoningAdapter()
    a = {e.external_id for e in await adapter.fetch()}
    b = {e.external_id for e in await adapter.fetch()}
    assert a == b
