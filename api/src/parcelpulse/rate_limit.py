"""Lightweight Redis-backed sliding-window rate limiter.

Used today by `POST /watchlists` to cap visitor-created watchlists at
5/IP/hour. The pattern is the same INCR-with-TTL approach as the circuit
breaker — atomic, no race, expires automatically.
"""

import redis.asyncio as redis_async

from parcelpulse.settings import settings


def _client() -> redis_async.Redis:
    return redis_async.from_url(settings.redis_url, decode_responses=True)


async def check_and_increment(
    key: str,
    *,
    limit: int,
    window_seconds: int,
    client: redis_async.Redis | None = None,
) -> tuple[bool, int]:
    """Returns (allowed, current_count). The first call inside a window sets the TTL."""
    r = client or _client()
    try:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window_seconds)
        return count <= limit, count
    finally:
        if client is None:
            await r.aclose()


async def reset(key: str, *, client: redis_async.Redis | None = None) -> None:
    r = client or _client()
    try:
        await r.delete(key)
    finally:
        if client is None:
            await r.aclose()
