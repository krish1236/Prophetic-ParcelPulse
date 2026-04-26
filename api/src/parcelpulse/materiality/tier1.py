"""Tier 1 — Haiku materiality screen.

For each Tier-0 candidate, ask Claude Haiku 4.5 (via tool-use for strict
structured output) whether the event is material to the watchlist's deal
thesis. Cached on `sha256(event_id || parcel_id || thesis_version)` so
re-runs over the same data are free and deterministic — the property the
Phase 7 replay slider depends on.
"""

import hashlib
import json
import logging
from typing import Any, Literal
from uuid import UUID

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.settings import settings

log = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5"

# Approximate per-call cost (USD). Haiku 4.5 pricing: ~$1/M input, ~$5/M output.
# A typical materiality screen is ~600 input + 80 output tokens.
HAIKU_COST_ESTIMATE_USD = 0.001


class MaterialityScreen(BaseModel):
    material: bool
    axis: Literal["zoning", "flood", "permit", "ownership", "market"]
    materiality_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str


_TOOL_SCHEMA: dict[str, Any] = {
    "name": "materiality_screen",
    "description": (
        "Decide whether a real-world change to a parcel is material to a "
        "homebuilder's deal thesis."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "material": {
                "type": "boolean",
                "description": "Whether this event is material to the thesis.",
            },
            "axis": {
                "type": "string",
                "enum": ["zoning", "flood", "permit", "ownership", "market"],
                "description": "Which materiality axis this event belongs to.",
            },
            "materiality_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "0=trivial, 100=deal-breaker.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Classifier confidence in this screen (0-1).",
            },
            "summary": {
                "type": "string",
                "description": "One sentence describing why or why not it matters.",
            },
        },
        "required": [
            "material",
            "axis",
            "materiality_score",
            "confidence",
            "summary",
        ],
    },
}

_PROMPT_TEMPLATE = """You evaluate whether a real-world change to a parcel is material to a homebuilder's deal thesis.

DEAL THESIS:
{thesis}

PARCEL CONTEXT:
APN: {apn}
County: {county_fips}
Zoning: {zoning}
Acres: {acres}
Address: {address}

EVENT:
Type: {event_type}
Source: {source}
Occurred: {occurred_at}
Payload: {payload_json}

Decide whether this event is material to the thesis. Be conservative: if you're not sure, mark non-material with low confidence rather than a false positive. A homebuilder will lose trust faster from one bad alert than from a missed minor signal."""


def cache_key(event_id: UUID, parcel_id: UUID, thesis_version: int) -> bytes:
    """Stable hash for the classifier cache. Bumping thesis_version invalidates."""
    h = hashlib.sha256()
    h.update(f"{event_id}:{parcel_id}:{thesis_version}".encode())
    return h.digest()


async def screen(
    event_id: UUID,
    parcel_id: UUID,
    watchlist_id: UUID,
    session: AsyncSession,
    *,
    client: anthropic.AsyncAnthropic | None = None,
    use_cache_only: bool = False,
) -> MaterialityScreen | None:
    """Classify whether an event is material to a watchlist's parcel.

    Cache-on-read first. If `use_cache_only=True` (Phase 7 replay path), never
    calls the live API — returns None on cache miss instead. Otherwise calls
    Haiku, validates, caches, and returns. Network or validation failures log
    and return None.
    """
    ctx = await _fetch_context(event_id, parcel_id, watchlist_id, session)
    if ctx is None:
        return None

    key = cache_key(event_id, parcel_id, ctx["thesis_version"])
    cached = await _cache_get(session, key)
    if cached is not None:
        return MaterialityScreen.model_validate(cached)
    if use_cache_only:
        return None

    client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    prompt = _PROMPT_TEMPLATE.format(
        thesis=ctx["deal_thesis"],
        apn=ctx["apn"],
        county_fips=ctx["county_fips"],
        zoning=ctx["zoning"] or "(unknown)",
        acres=ctx["area_acres"] or "(unknown)",
        address=ctx["site_address"] or "(unknown)",
        event_type=ctx["event_type"],
        source=ctx["source"],
        occurred_at=ctx["occurred_at"].isoformat(),
        payload_json=json.dumps(ctx["payload"], indent=2, default=str),
    )

    try:
        response = await client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "materiality_screen"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError:
        log.exception("anthropic api error during tier1 screen")
        return None

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "materiality_screen":
            try:
                screened = MaterialityScreen.model_validate(block.input)
            except Exception:
                log.exception("tool_use input failed validation")
                return None
            await _cache_put(session, key, screened, cost_usd=HAIKU_COST_ESTIMATE_USD)
            return screened

    log.warning("no materiality_screen tool_use block in response")
    return None


async def _fetch_context(
    event_id: UUID,
    parcel_id: UUID,
    watchlist_id: UUID,
    session: AsyncSession,
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("""
                SELECT
                    e.event_type, e.source, e.payload, e.occurred_at,
                    p.apn, p.county_fips,
                    p.attrs->>'zoning'       AS zoning,
                    p.attrs->>'area_acres'   AS area_acres,
                    p.attrs->>'site_address' AS site_address,
                    w.deal_thesis, w.thesis_version
                FROM events e
                CROSS JOIN parcels p
                CROSS JOIN watchlists w
                WHERE e.event_id = :eid
                  AND p.parcel_id = :pid
                  AND w.watchlist_id = :wlid
            """),
            {
                "eid": str(event_id),
                "pid": str(parcel_id),
                "wlid": str(watchlist_id),
            },
        )
    ).mappings().first()
    return dict(row) if row else None


async def _cache_get(session: AsyncSession, key: bytes) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                "SELECT response FROM classifier_cache "
                "WHERE cache_key = :k AND tier = 'haiku'"
            ),
            {"k": key},
        )
    ).scalar_one_or_none()
    return row


async def _cache_put(
    session: AsyncSession,
    key: bytes,
    screened: MaterialityScreen,
    *,
    cost_usd: float,
) -> None:
    await session.execute(
        text("""
            INSERT INTO classifier_cache (cache_key, tier, response, cost_usd)
            VALUES (:k, 'haiku', CAST(:r AS jsonb), :c)
            ON CONFLICT (cache_key) DO NOTHING
        """),
        {"k": key, "r": screened.model_dump_json(), "c": cost_usd},
    )
    await session.commit()
