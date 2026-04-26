"""Tests for the per-source circuit breaker (Redis-backed)."""

import asyncio

import pytest_asyncio
import redis.asyncio as redis_async

from parcelpulse.circuit_breaker import (
    is_paused,
    record_failure,
    record_success,
    reset,
    state_snapshot,
)
from parcelpulse.settings import settings

TEST_SOURCE = "test_cb_source"


@pytest_asyncio.fixture
async def redis_client():
    client = redis_async.from_url(settings.redis_url, decode_responses=True)
    await reset(TEST_SOURCE, client=client)
    yield client
    await reset(TEST_SOURCE, client=client)
    await client.aclose()


async def test_starts_unpaused(redis_client):
    assert (await is_paused(TEST_SOURCE, client=redis_client)) is False


async def test_record_failure_below_threshold_does_not_pause(redis_client):
    tripped = await record_failure(TEST_SOURCE, client=redis_client)
    assert tripped is False
    assert (await is_paused(TEST_SOURCE, client=redis_client)) is False
    snap = await state_snapshot(TEST_SOURCE, client=redis_client)
    assert snap["fail_count"] == 1
    assert snap["paused"] is False


async def test_record_failure_at_threshold_pauses(redis_client):
    # Default threshold is 3 — record 3 consecutive failures.
    for i in range(settings.circuit_breaker_failure_threshold):
        tripped = await record_failure(TEST_SOURCE, client=redis_client)
        if i + 1 == settings.circuit_breaker_failure_threshold:
            assert tripped is True
        else:
            assert tripped is False
    assert (await is_paused(TEST_SOURCE, client=redis_client)) is True


async def test_record_success_clears_failure_counter(redis_client):
    await record_failure(TEST_SOURCE, client=redis_client)
    await record_failure(TEST_SOURCE, client=redis_client)
    snap = await state_snapshot(TEST_SOURCE, client=redis_client)
    assert snap["fail_count"] == 2
    await record_success(TEST_SOURCE, client=redis_client)
    snap = await state_snapshot(TEST_SOURCE, client=redis_client)
    assert snap["fail_count"] == 0
    # Not yet paused, so success leaves it unpaused.
    assert snap["paused"] is False


async def test_success_after_pause_does_not_unpause(redis_client):
    # Trip the breaker.
    for _ in range(settings.circuit_breaker_failure_threshold):
        await record_failure(TEST_SOURCE, client=redis_client)
    assert (await is_paused(TEST_SOURCE, client=redis_client)) is True
    # A single recovery success clears the counter but the pause stands until TTL.
    await record_success(TEST_SOURCE, client=redis_client)
    assert (await is_paused(TEST_SOURCE, client=redis_client)) is True


async def test_reset_clears_pause_and_count(redis_client):
    for _ in range(settings.circuit_breaker_failure_threshold):
        await record_failure(TEST_SOURCE, client=redis_client)
    await reset(TEST_SOURCE, client=redis_client)
    snap = await state_snapshot(TEST_SOURCE, client=redis_client)
    assert snap == {"source": TEST_SOURCE, "fail_count": 0, "paused": False}


# Light real-end-to-end: sanity-check that two concurrent failures both increment
# (Redis INCR is atomic, but worth proving the integration end-to-end).
async def test_concurrent_failures_increment_atomically(redis_client):
    await asyncio.gather(*[
        record_failure(TEST_SOURCE, client=redis_client) for _ in range(2)
    ])
    snap = await state_snapshot(TEST_SOURCE, client=redis_client)
    assert snap["fail_count"] == 2
