"""Per-source ingestion circuit breaker, persisted in Redis.

Both the scheduler (which records fetch outcomes) and the API (`/health`,
which displays paused state) consult the same Redis keys, so a paused source
shows up in /health within one tick of the scheduler hitting the threshold.

State per source `s`:
  cb:{s}:fail_count   — INCR-and-EXPIRE counter inside the rolling window
  cb:{s}:paused_until — set when threshold is reached; auto-expires on its own

A success clears `fail_count` (paused_until is left alone — it expires by TTL,
which is the right behavior: a one-off success while in a pause window
shouldn't immediately re-arm the source).
"""

import logging
from typing import Any

import redis.asyncio as redis_async

from parcelpulse.settings import settings

log = logging.getLogger(__name__)


def _client() -> redis_async.Redis:
    return redis_async.from_url(settings.redis_url, decode_responses=True)


def _fail_key(source: str) -> str:
    return f"cb:{source}:fail_count"


def _pause_key(source: str) -> str:
    return f"cb:{source}:paused_until"


async def record_failure(source: str, *, client: redis_async.Redis | None = None) -> bool:
    """Bump the failure counter; if it crosses the threshold, set the pause key.
    Returns True iff the source is now paused as a result of this failure."""
    r = client or _client()
    try:
        count = await r.incr(_fail_key(source))
        # Set TTL only on the first increment so the rolling window is honored.
        if count == 1:
            await r.expire(
                _fail_key(source),
                settings.circuit_breaker_failure_window_seconds,
            )
        if count >= settings.circuit_breaker_failure_threshold:
            await r.set(
                _pause_key(source),
                "1",
                ex=settings.circuit_breaker_pause_seconds,
            )
            log.warning(
                "circuit breaker tripped for source=%s after %d failures",
                source,
                count,
            )
            return True
        return False
    finally:
        if client is None:
            await r.aclose()


async def record_success(source: str, *, client: redis_async.Redis | None = None) -> None:
    r = client or _client()
    try:
        await r.delete(_fail_key(source))
    finally:
        if client is None:
            await r.aclose()


async def is_paused(source: str, *, client: redis_async.Redis | None = None) -> bool:
    r = client or _client()
    try:
        return bool(await r.exists(_pause_key(source)))
    finally:
        if client is None:
            await r.aclose()


async def paused_for_all(
    sources: list[str], *, client: redis_async.Redis | None = None
) -> dict[str, bool]:
    r = client or _client()
    try:
        out: dict[str, bool] = {}
        for s in sources:
            out[s] = bool(await r.exists(_pause_key(s)))
        return out
    finally:
        if client is None:
            await r.aclose()


async def reset(source: str, *, client: redis_async.Redis | None = None) -> None:
    """Clear both keys for a source. Used by tests."""
    r = client or _client()
    try:
        await r.delete(_fail_key(source))
        await r.delete(_pause_key(source))
    finally:
        if client is None:
            await r.aclose()


async def state_snapshot(
    source: str, *, client: redis_async.Redis | None = None
) -> dict[str, Any]:
    """Diagnostic — return the current counter + pause state for one source."""
    r = client or _client()
    try:
        fail_str = await r.get(_fail_key(source))
        return {
            "source": source,
            "fail_count": int(fail_str) if fail_str is not None else 0,
            "paused": bool(await r.exists(_pause_key(source))),
        }
    finally:
        if client is None:
            await r.aclose()
