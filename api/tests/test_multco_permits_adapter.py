import json
from pathlib import Path

import httpx
import pytest

from parcelpulse.adapters.base import CanonicalEvent
from parcelpulse.adapters.multco_permits import (
    MultcoPermitsAdapter,
    _classify_event_type,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "multco_permits_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _mock_client(payload: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_returns_canonical_events_for_each_feature():
    fixture = _load_fixture()
    expected = len(fixture["features"])
    adapter = MultcoPermitsAdapter(http_client=_mock_client(fixture))
    events = await adapter.fetch()
    assert len(events) == expected
    assert all(isinstance(e, CanonicalEvent) for e in events)
    assert all(e.source == "multco_permits" for e in events)


async def test_fetch_uses_folder_rsn_as_external_id():
    fixture = _load_fixture()
    adapter = MultcoPermitsAdapter(http_client=_mock_client(fixture))
    events = await adapter.fetch()
    for ev, feat in zip(events, fixture["features"], strict=True):
        assert ev.external_id == str(feat["properties"]["FOLDER_RSN"])


async def test_fetch_carries_geometry_through():
    fixture = _load_fixture()
    adapter = MultcoPermitsAdapter(http_client=_mock_client(fixture))
    events = await adapter.fetch()
    for ev, feat in zip(events, fixture["features"], strict=True):
        assert ev.geometry == feat.get("geometry")


async def test_fetch_skips_features_missing_required_fields():
    payload = {
        "features": [
            # complete record
            {
                "geometry": {"type": "Point", "coordinates": [-122.6, 45.5]},
                "properties": {
                    "FOLDER_RSN": 1,
                    "INTAKE_COMPLETE_DATE": 1577836800000,
                    "WORK_TYPE": "New",
                },
            },
            # missing FOLDER_RSN
            {"properties": {"INTAKE_COMPLETE_DATE": 1577836800000, "WORK_TYPE": "New"}},
            # missing date
            {"properties": {"FOLDER_RSN": 2, "WORK_TYPE": "Alteration"}},
        ]
    }
    adapter = MultcoPermitsAdapter(http_client=_mock_client(payload))
    events = await adapter.fetch()
    assert len(events) == 1
    assert events[0].external_id == "1"


@pytest.mark.parametrize(
    "work_type,expected",
    [
        ("New Construction", "permit.new"),
        ("Alteration", "permit.alteration"),
        ("Demolition", "permit.demolition"),
        ("Addition", "permit.addition"),
        ("Repair / Replacement", "permit.repair"),
        ("", "permit.other"),
        (None, "permit.other"),
        ("Some weird thing", "permit.other"),
    ],
)
def test_classify_event_type(work_type, expected):
    assert _classify_event_type({"WORK_TYPE": work_type}) == expected


async def test_payload_hash_distinguishes_records():
    fixture = _load_fixture()
    adapter = MultcoPermitsAdapter(http_client=_mock_client(fixture))
    events = await adapter.fetch()
    hashes = {e.payload_hash() for e in events}
    # Each feature has a different FOLDER_RSN so payload_hashes must all differ.
    assert len(hashes) == len(events)
