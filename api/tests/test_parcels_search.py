from uuid import UUID

import httpx

from tests.conftest import TEST_APN, TEST_APN_2


async def test_search_by_apn_returns_one(
    http_client: httpx.AsyncClient,
    seeded_parcels: list[UUID],
):
    r = await http_client.get(f"/parcels/search?apn={TEST_APN}")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["apn"] == TEST_APN
    # Centroid was inserted as POINT(-100.05 40.05)
    assert item["centroid"] == [-100.05, 40.05]


async def test_search_by_bbox_intersects_both_parcels(
    http_client: httpx.AsyncClient,
    seeded_parcels: list[UUID],
):
    # Bbox that contains both seeded test parcels.
    r = await http_client.get("/parcels/search?bbox=-100.4,39.9,-99.9,40.2")
    assert r.status_code == 200
    body = r.json()
    apns = {item["apn"] for item in body["items"]}
    assert TEST_APN in apns
    assert TEST_APN_2 in apns


async def test_search_by_bbox_intersects_only_one(
    http_client: httpx.AsyncClient,
    seeded_parcels: list[UUID],
):
    # Bbox that only overlaps the first parcel (centered near -100.05).
    r = await http_client.get("/parcels/search?bbox=-100.15,39.95,-100.0,40.15")
    assert r.status_code == 200
    body = r.json()
    apns = {item["apn"] for item in body["items"]}
    assert TEST_APN in apns
    assert TEST_APN_2 not in apns


async def test_search_without_apn_or_bbox_returns_400(http_client: httpx.AsyncClient):
    r = await http_client.get("/parcels/search")
    assert r.status_code == 400


async def test_search_with_oversized_bbox_returns_400(http_client: httpx.AsyncClient):
    # > 1 degree in either direction is rejected.
    r = await http_client.get("/parcels/search?bbox=-130,30,-100,50")
    assert r.status_code == 400


async def test_search_pagination_limit_offset(
    http_client: httpx.AsyncClient,
    seeded_parcels: list[UUID],
):
    r = await http_client.get(
        "/parcels/search?bbox=-100.4,39.9,-99.9,40.2&limit=1&offset=0"
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert body["total"] >= 2  # both seeded parcels match
