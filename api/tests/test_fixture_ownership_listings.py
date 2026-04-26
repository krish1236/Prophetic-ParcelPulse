"""Smoke tests for the ownership + listings fixture adapters.

The shared `load_fixture_events` helper is exercised by test_fixture_zoning_adapter;
here we just verify the new adapters wire to their respective fixture files
and emit canonical events with the expected source names + types.
"""

from parcelpulse.adapters.base import CanonicalEvent
from parcelpulse.adapters.fixture_listings import FixtureListingsAdapter
from parcelpulse.adapters.fixture_ownership import FixtureOwnershipAdapter


async def test_ownership_adapter_emits_ownership_events():
    events = await FixtureOwnershipAdapter().fetch()
    assert len(events) >= 1
    assert all(isinstance(e, CanonicalEvent) for e in events)
    assert all(e.source == "fixture_ownership" for e in events)
    assert all(e.event_type.startswith("ownership.") for e in events)


async def test_listings_adapter_emits_listing_or_market_events():
    events = await FixtureListingsAdapter().fetch()
    assert len(events) >= 1
    assert all(isinstance(e, CanonicalEvent) for e in events)
    assert all(e.source == "fixture_listings" for e in events)
    assert all(e.event_type in {"ownership.listing", "market.comp"} for e in events)


async def test_fixture_adapters_external_ids_are_stable():
    a1 = {e.external_id for e in await FixtureOwnershipAdapter().fetch()}
    a2 = {e.external_id for e in await FixtureOwnershipAdapter().fetch()}
    assert a1 == a2
    b1 = {e.external_id for e in await FixtureListingsAdapter().fetch()}
    b2 = {e.external_id for e in await FixtureListingsAdapter().fetch()}
    assert b1 == b2


async def test_fixture_adapters_carry_geometry():
    for events in [
        await FixtureOwnershipAdapter().fetch(),
        await FixtureListingsAdapter().fetch(),
    ]:
        geoms = [e.geometry for e in events if e.geometry is not None]
        assert len(geoms) >= 1
        for g in geoms:
            assert g["type"] == "Point"
            assert len(g["coordinates"]) == 2
