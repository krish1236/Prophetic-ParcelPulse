"""Tests for the Redis-backed rate limiter and POST /watchlists rate cap."""

import httpx
import pytest_asyncio
import redis.asyncio as redis_async
from sqlalchemy import text

from parcelpulse.db import SessionLocal
from parcelpulse.rate_limit import check_and_increment, reset
from parcelpulse.settings import settings


@pytest_asyncio.fixture
async def redis_client():
    client = redis_async.from_url(settings.redis_url, decode_responses=True)
    yield client
    await client.aclose()


async def test_check_and_increment_allows_under_limit(redis_client):
    key = "rl:test:under"
    await reset(key, client=redis_client)
    for i in range(3):
        allowed, count = await check_and_increment(
            key, limit=5, window_seconds=60, client=redis_client
        )
        assert allowed is True
        assert count == i + 1
    await reset(key, client=redis_client)


async def test_check_and_increment_rejects_over_limit(redis_client):
    key = "rl:test:over"
    await reset(key, client=redis_client)
    for _ in range(5):
        allowed, _ = await check_and_increment(
            key, limit=5, window_seconds=60, client=redis_client
        )
        assert allowed is True
    allowed, count = await check_and_increment(
        key, limit=5, window_seconds=60, client=redis_client
    )
    assert allowed is False
    assert count == 6
    await reset(key, client=redis_client)


async def test_post_watchlists_returns_429_after_limit(http_client: httpx.AsyncClient):
    client = redis_async.from_url(settings.redis_url, decode_responses=True)
    # Reset any prior limit state for this client IP. ASGITransport reports
    # client.host as 'testclient' which is what _client_ip returns here.
    await reset("rl:wl_create:127.0.0.1", client=client)

    payload = {
        "name": "rl",
        "deal_thesis": "Townhomes 8-12 du/ac, must clear FEMA Zone X.",
    }
    created_ids: list[str] = []
    for _ in range(settings.watchlist_create_rate_limit):
        r = await http_client.post("/watchlists", json=payload)
        assert r.status_code == 200
        created_ids.append(r.json()["watchlist_id"])

    r = await http_client.post("/watchlists", json=payload)
    assert r.status_code == 429
    assert "rate limit" in r.json()["detail"].lower()

    # Cleanup: drop test watchlists + reset limiter.
    async with SessionLocal() as session:
        for wid in created_ids:
            await session.execute(
                text("DELETE FROM watchlists WHERE watchlist_id = :w"),
                {"w": wid},
            )
        await session.commit()
    await reset("rl:wl_create:127.0.0.1", client=client)
    await client.aclose()
