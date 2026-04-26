"""Tests for Tier 2 Sonnet decision-trace generator.

Anthropic is mocked; tests never touch the live API. Covers cache miss/hit,
use_cache_only escape hatch, hallucinated-URL rejection, and that bad output
is never cached.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.materiality.tier1 import MaterialityScreen
from parcelpulse.materiality.tier2 import (
    DecisionTrace,
    build_allowed_urls,
    cache_key,
    generate_trace,
)

TEST_WORKSPACE = UUID("00000000-0000-0000-0000-0000ffff0001")
TEST_FIPS = "99994"
PARCEL_WKT = (
    "POLYGON((-100.0005 39.9995, -100.0005 40.0005, "
    "-99.9995 40.0005, -99.9995 39.9995, -100.0005 39.9995))"
)


async def _seed(session: AsyncSession) -> tuple[UUID, UUID, UUID]:
    parcel_id = (
        await session.execute(
            text(
                "INSERT INTO parcels (county_fips, apn, geom, centroid, attrs) "
                f"VALUES (:f, :apn, ST_Multi(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                f"ST_Centroid(ST_GeomFromText('{PARCEL_WKT}', 4326)), "
                "'{\"zoning\":\"R5\",\"area_acres\":\"1.5\",\"site_address\":\"42 X ST\"}'::jsonb"
                ") RETURNING parcel_id"
            ),
            {"f": TEST_FIPS, "apn": f"T-{uuid4()}"},
        )
    ).scalar_one()
    wl_id = (
        await session.execute(
            text(
                "INSERT INTO watchlists (workspace_id, name, deal_thesis, thesis_version) "
                "VALUES (:ws, 'tier2 test', 'Townhomes 8-12 du/ac.', 1) "
                "RETURNING watchlist_id"
            ),
            {"ws": str(TEST_WORKSPACE)},
        )
    ).scalar_one()
    import json as _json
    event_id = (
        await session.execute(
            text(
                "INSERT INTO events (source, external_id, payload_hash, event_type, "
                "payload, geometry, occurred_at) "
                "VALUES ('multco_permits', :eid, :h, 'permit.demolition', "
                "CAST(:payload AS jsonb), ST_GeomFromText('POINT(-100 40)', 4326), :occ) "
                "RETURNING event_id"
            ),
            {
                "eid": "trigger-1",
                "h": uuid4().bytes,
                "payload": _json.dumps({"FOLDER_RSN": 12345, "WORK_TYPE": "Demolition"}),
                "occ": datetime.now(UTC),
            },
        )
    ).scalar_one()
    await session.commit()
    return event_id, parcel_id, wl_id


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db_session: AsyncSession):
    yield
    await db_session.execute(
        text("DELETE FROM watchlists WHERE workspace_id = :ws"),
        {"ws": str(TEST_WORKSPACE)},
    )
    await db_session.execute(
        text("DELETE FROM parcels WHERE county_fips = :f"), {"f": TEST_FIPS}
    )
    await db_session.execute(
        text("DELETE FROM events WHERE source = 'multco_permits' AND external_id = 'trigger-1'")
    )
    await db_session.execute(text("DELETE FROM classifier_cache WHERE tier = 'sonnet'"))
    await db_session.commit()


def _fake_client(payload: dict) -> SimpleNamespace:
    block = SimpleNamespace(type="tool_use", name="decision_trace", input=payload)
    response = SimpleNamespace(content=[block])
    return SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=response))
    )


# Helper: build a valid trace payload pinned to the FOLDER_RSN allowed URL.
def _valid_trace(allowed_url: str) -> dict:
    return {
        "what_changed": "Demolition permit issued on parcel.",
        "why_it_matters": "Demo on a watched parcel changes assemblage thesis.",
        "evidence": [
            {
                "label": "permit",
                "source_url": allowed_url,
                "snippet": "Demolition permit issued.",
                "captured_at": None,
            }
        ],
        "next_step": {
            "action": "Reach out to demolition applicant.",
            "urgency": "this_week",
            "owner_role": "land_acquisition_lead",
        },
    }


SCREEN = MaterialityScreen(
    material=True,
    axis="permit",
    materiality_score=75,
    confidence=0.85,
    summary="Material change.",
)


async def test_calls_anthropic_and_returns_trace_on_cache_miss(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed(db_session)
    allowed_url = "https://www.portlandmaps.com/detail/permit/12345/"
    client = _fake_client(_valid_trace(allowed_url))
    trace = await generate_trace(
        event_id, parcel_id, wl_id, db_session, SCREEN, client=client
    )
    assert isinstance(trace, DecisionTrace)
    assert trace.evidence[0].source_url == allowed_url
    assert trace.next_step.urgency == "this_week"
    client.messages.create.assert_awaited_once()


async def test_returns_cached_trace_without_calling_api(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed(db_session)
    allowed_url = "https://www.portlandmaps.com/detail/permit/12345/"
    client = _fake_client(_valid_trace(allowed_url))

    first = await generate_trace(
        event_id, parcel_id, wl_id, db_session, SCREEN, client=client
    )
    assert first is not None
    assert client.messages.create.await_count == 1

    second = await generate_trace(
        event_id, parcel_id, wl_id, db_session, SCREEN, client=client
    )
    assert second == first
    assert client.messages.create.await_count == 1


async def test_use_cache_only_returns_none_on_miss(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed(db_session)
    client = _fake_client(_valid_trace("ignored"))
    trace = await generate_trace(
        event_id,
        parcel_id,
        wl_id,
        db_session,
        SCREEN,
        client=client,
        use_cache_only=True,
    )
    assert trace is None
    client.messages.create.assert_not_awaited()


async def test_rejects_hallucinated_evidence_url(db_session: AsyncSession):
    event_id, parcel_id, wl_id = await _seed(db_session)
    bad = _valid_trace("https://example.com/not-in-allowed-list")
    client = _fake_client(bad)
    trace = await generate_trace(
        event_id, parcel_id, wl_id, db_session, SCREEN, client=client
    )
    assert trace is None
    cached = (
        await db_session.execute(
            text("SELECT count(*) FROM classifier_cache WHERE tier = 'sonnet'")
        )
    ).scalar_one()
    assert cached == 0


async def test_invalid_tool_output_returns_none_and_does_not_cache(
    db_session: AsyncSession,
):
    event_id, parcel_id, wl_id = await _seed(db_session)
    bad = {"what_changed": "x"}  # missing required fields
    client = _fake_client(bad)
    trace = await generate_trace(
        event_id, parcel_id, wl_id, db_session, SCREEN, client=client
    )
    assert trace is None
    cached = (
        await db_session.execute(
            text("SELECT count(*) FROM classifier_cache WHERE tier = 'sonnet'")
        )
    ).scalar_one()
    assert cached == 0


def test_cache_key_changes_with_thesis_version():
    eid = uuid4()
    pid = uuid4()
    a = cache_key(eid, pid, 1)
    b = cache_key(eid, pid, 2)
    assert a != b


def test_tier2_cache_key_distinct_from_tier1():
    """Tier 2 must use a different cache key namespace so haiku and sonnet rows
    coexist in classifier_cache (cache_key is the table's PRIMARY KEY)."""
    from parcelpulse.materiality.tier1 import cache_key as haiku_key

    eid = uuid4()
    pid = uuid4()
    assert cache_key(eid, pid, 1) != haiku_key(eid, pid, 1)


def test_build_allowed_urls_uses_portland_maps_when_present():
    events = [
        {
            "source": "multco_permits",
            "external_id": "1",
            "payload": {"PORTLAND_MAPS_URL": "https://www.portlandmaps.com/x"},
        },
    ]
    urls = build_allowed_urls(events)
    assert urls == {"multco_permits:1": "https://www.portlandmaps.com/x"}


def test_build_allowed_urls_constructs_from_folder_rsn():
    events = [
        {
            "source": "multco_permits",
            "external_id": "2",
            "payload": {"FOLDER_RSN": 99},
        },
    ]
    urls = build_allowed_urls(events)
    assert urls["multco_permits:2"] == "https://www.portlandmaps.com/detail/permit/99/"


def test_build_allowed_urls_falls_back_to_placeholder_for_unknown_source():
    events = [{"source": "fixture_listings", "external_id": "abc", "payload": {}}]
    urls = build_allowed_urls(events)
    assert urls == {"fixture_listings:abc": "https://example.com/source/fixture_listings/abc"}
