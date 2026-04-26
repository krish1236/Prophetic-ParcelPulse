"""Tier 2 — Sonnet decision-trace generator.

For alerts that pass the Tier 1 materiality threshold, Sonnet 4.6 produces
a structured decision trace (what changed / why it matters / evidence /
suggested next step). The trace is what the user sees on the alert detail
page; Phase 7's replay slider reads cached traces, never recomputes.

Closed-set evidence URLs (per Phase 5 risk doc): the prompt includes the
exact set of URLs Sonnet may cite, derived from the parcel's recent event
history. Outputs that reference URLs outside the set are rejected and
nothing is cached, so a hallucinated link can't poison the demo.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import anthropic
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.materiality.tier1 import MaterialityScreen
from parcelpulse.settings import settings

log = logging.getLogger(__name__)

SONNET_MODEL = "claude-sonnet-4-6"

# Approximate per-call cost (USD). Sonnet 4.6 pricing: ~$3/M input, ~$15/M output.
# A typical decision trace is ~1000 input + 250 output tokens.
SONNET_COST_ESTIMATE_USD = 0.007

Urgency = Literal["now", "this_week", "fyi"]


class Evidence(BaseModel):
    label: str
    source_url: str
    snippet: str
    captured_at: datetime | None = None


class NextStep(BaseModel):
    action: str
    urgency: Urgency
    owner_role: str


class DecisionTrace(BaseModel):
    what_changed: str
    why_it_matters: str
    evidence: list[Evidence]
    next_step: NextStep


_TOOL_SCHEMA: dict[str, Any] = {
    "name": "decision_trace",
    "description": (
        "Generate a structured briefing card explaining a material parcel-level "
        "change to a homebuilder's land acquisition team."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "what_changed": {
                "type": "string",
                "description": "1-2 sentences in plain English; what concretely changed.",
            },
            "why_it_matters": {
                "type": "string",
                "description": "1-2 sentences referencing the deal thesis directly.",
            },
            "evidence": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "source_url": {
                            "type": "string",
                            "description": "MUST be one of the allowed URLs from the prompt.",
                        },
                        "snippet": {"type": "string"},
                        "captured_at": {"type": ["string", "null"]},
                    },
                    "required": ["label", "source_url", "snippet"],
                },
            },
            "next_step": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "urgency": {"type": "string", "enum": ["now", "this_week", "fyi"]},
                    "owner_role": {"type": "string"},
                },
                "required": ["action", "urgency", "owner_role"],
            },
        },
        "required": ["what_changed", "why_it_matters", "evidence", "next_step"],
    },
}


_PROMPT_TEMPLATE = """You produce a structured decision trace for a material parcel-level event.

The trace is shown on a homebuilder's land acquisition briefing card. Be concrete and terse. Reference the deal thesis directly. Do NOT speculate beyond the evidence provided. Each evidence.source_url MUST be picked from the allowed list — if you can't justify the trace using only those URLs, set evidence to a single item that quotes the triggering event.

DEAL THESIS:
{thesis}

PARCEL CONTEXT:
APN: {apn}
County: {county_fips}
Zoning: {zoning}
Acres: {acres}
Address: {address}

TRIGGERING EVENT:
Type: {event_type}
Source: {source}
Occurred: {occurred_at}
Payload: {payload_json}

PRIOR TIER-1 SCREEN:
material: {tier1_material}
axis: {tier1_axis}
score: {tier1_score}
summary: {tier1_summary}

PARCEL EVENT HISTORY (last 30 days, most recent first; up to 25 records):
{event_history}

ALLOWED EVIDENCE URLS — pick source_url values from this list and ONLY this list:
{allowed_urls}

Pick urgency: 'now' if action is needed today (legal exposure, missed window), 'this_week' if material to a current diligence cycle, 'fyi' otherwise."""


def cache_key(
    event_id: UUID, parcel_id: UUID, thesis_version: int
) -> bytes:
    """Tier 2 cache key. Distinct from Tier 1 so haiku and sonnet rows coexist
    in classifier_cache for the same (event, parcel, thesis_version)."""
    h = hashlib.sha256()
    h.update(f"sonnet:{event_id}:{parcel_id}:{thesis_version}".encode())
    return h.digest()


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


async def _fetch_event_history(
    parcel_id: UUID, session: AsyncSession, *, days: int = 30, limit: int = 25
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text("""
                SELECT e.event_id, e.source, e.external_id, e.event_type,
                       e.payload, e.occurred_at
                FROM events e
                WHERE e.geometry IS NOT NULL
                  AND ST_DWithin(
                      e.geometry::geography,
                      (SELECT geom::geography FROM parcels WHERE parcel_id = :pid),
                      152.4
                  )
                  AND e.occurred_at >= now() - make_interval(days => :days)
                ORDER BY e.occurred_at DESC
                LIMIT :lim
            """),
            {"pid": str(parcel_id), "days": days, "lim": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def build_allowed_urls(events: list[dict[str, Any]]) -> dict[str, str]:
    """Build the closed set of allowed evidence URLs keyed by display label.

    For permits, prefer the upstream PORTLAND_MAPS_URL when present; otherwise
    construct a deep link from FOLDER_RSN. Other sources fall back to a
    deterministic placeholder. Sonnet must pick from the values of this dict.
    """
    out: dict[str, str] = {}
    for ev in events:
        payload = ev.get("payload") or {}
        url: str | None = None
        if ev["source"] == "multco_permits":
            url = payload.get("PORTLAND_MAPS_URL")
            if not url:
                folder_rsn = payload.get("FOLDER_RSN")
                if folder_rsn is not None:
                    url = f"https://www.portlandmaps.com/detail/permit/{folder_rsn}/"
        if url is None:
            url = f"https://example.com/source/{ev['source']}/{ev['external_id']}"
        label = f"{ev['source']}:{ev['external_id']}"
        out[label] = url
    return out


def _format_history(events: list[dict[str, Any]]) -> str:
    if not events:
        return "(none)"
    lines = []
    for e in events:
        lines.append(
            f"  - {e['occurred_at'].isoformat()}  {e['event_type']:24s}  "
            f"{e['source']}:{e['external_id']}"
        )
    return "\n".join(lines)


def _format_urls(allowed_urls: dict[str, str]) -> str:
    if not allowed_urls:
        return "(none)"
    return "\n".join(f"  - {label} → {url}" for label, url in allowed_urls.items())


async def _cache_get(session: AsyncSession, key: bytes) -> dict[str, Any] | None:
    return (
        await session.execute(
            text(
                "SELECT response FROM classifier_cache "
                "WHERE cache_key = :k AND tier = 'sonnet'"
            ),
            {"k": key},
        )
    ).scalar_one_or_none()


async def _cache_put(
    session: AsyncSession,
    key: bytes,
    trace: DecisionTrace,
    *,
    cost_usd: float,
) -> None:
    await session.execute(
        text("""
            INSERT INTO classifier_cache (cache_key, tier, response, cost_usd)
            VALUES (:k, 'sonnet', CAST(:r AS jsonb), :c)
            ON CONFLICT (cache_key) DO NOTHING
        """),
        {"k": key, "r": trace.model_dump_json(), "c": cost_usd},
    )
    await session.commit()


async def generate_trace(
    event_id: UUID,
    parcel_id: UUID,
    watchlist_id: UUID,
    session: AsyncSession,
    tier1_screen: MaterialityScreen,
    *,
    client: anthropic.AsyncAnthropic | None = None,
    use_cache_only: bool = False,
) -> DecisionTrace | None:
    """Generate (or fetch cached) decision trace for one alert.

    Cache-on-read first. `use_cache_only=True` (Phase 7 replay) returns None
    on miss instead of calling the live API. Returns None on transport,
    validation, or hallucinated-URL failures (nothing cached in those cases).
    """
    ctx = await _fetch_context(event_id, parcel_id, watchlist_id, session)
    if ctx is None:
        return None

    key = cache_key(event_id, parcel_id, ctx["thesis_version"])
    cached = await _cache_get(session, key)
    if cached is not None:
        return DecisionTrace.model_validate(cached)
    if use_cache_only:
        return None

    history = await _fetch_event_history(parcel_id, session)
    allowed_urls = build_allowed_urls(history)
    allowed_url_set = set(allowed_urls.values())

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
        tier1_material=tier1_screen.material,
        tier1_axis=tier1_screen.axis,
        tier1_score=tier1_screen.materiality_score,
        tier1_summary=tier1_screen.summary,
        event_history=_format_history(history),
        allowed_urls=_format_urls(allowed_urls),
    )

    try:
        response = await client.messages.create(
            model=SONNET_MODEL,
            max_tokens=2048,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "decision_trace"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError:
        log.exception("anthropic api error during tier2 trace")
        return None

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "decision_trace":
            try:
                trace = DecisionTrace.model_validate(block.input)
            except Exception:
                log.exception("decision_trace input failed validation")
                return None
            for ev in trace.evidence:
                if ev.source_url not in allowed_url_set:
                    log.warning(
                        "rejecting hallucinated evidence URL: %s (not in allowed set of %d)",
                        ev.source_url,
                        len(allowed_url_set),
                    )
                    return None
            await _cache_put(session, key, trace, cost_usd=SONNET_COST_ESTIMATE_USD)
            return trace

    log.warning("no decision_trace tool_use block in response")
    return None
