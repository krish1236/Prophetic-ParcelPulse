import json
from pathlib import Path

import httpx

from parcelpulse.adapters.base import CanonicalEvent
from parcelpulse.adapters.fema_nfhl import FemaNfhlAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "fema_nfhl_sample.json"


def _mock_client(payload: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_returns_canonical_events_for_each_lomr():
    fixture = json.loads(FIXTURE.read_text())
    adapter = FemaNfhlAdapter(http_client=_mock_client(fixture))
    events = await adapter.fetch()
    assert len(events) == len(fixture["features"])
    assert all(isinstance(e, CanonicalEvent) for e in events)
    assert all(e.source == "fema_nfhl" for e in events)
    assert all(e.event_type == "flood.lomr" for e in events)


async def test_fetch_uses_lomr_id_as_external_id():
    fixture = json.loads(FIXTURE.read_text())
    adapter = FemaNfhlAdapter(http_client=_mock_client(fixture))
    events = await adapter.fetch()
    for ev, feat in zip(events, fixture["features"], strict=True):
        assert ev.external_id == str(feat["properties"]["LOMR_ID"])


async def test_fetch_skips_features_missing_required_fields():
    payload = {
        "features": [
            {
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {
                    "LOMR_ID": "X1",
                    "EFF_DATE": 1577836800000,
                    "CASE_NO": "24-X",
                    "STATUS": "Effective",
                },
            },
            # missing LOMR_ID
            {"properties": {"EFF_DATE": 1577836800000}},
            # missing EFF_DATE
            {"properties": {"LOMR_ID": "X2"}},
        ]
    }
    adapter = FemaNfhlAdapter(http_client=_mock_client(payload))
    events = await adapter.fetch()
    assert len(events) == 1
    assert events[0].external_id == "X1"


async def test_payload_hash_distinguishes_records():
    fixture = json.loads(FIXTURE.read_text())
    adapter = FemaNfhlAdapter(http_client=_mock_client(fixture))
    events = await adapter.fetch()
    hashes = {e.payload_hash() for e in events}
    assert len(hashes) == len(events)
