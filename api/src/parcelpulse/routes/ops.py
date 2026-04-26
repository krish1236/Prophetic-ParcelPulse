"""Engineering ops dashboard endpoints (consumed by /admin/ops on the web).

Gating: when `settings.ops_token` is set (prod), every /admin/ops/* request
must include matching `X-Ops-Token`. When empty (dev), no auth — convenient
for the local demo.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.db import get_session
from parcelpulse.health import source_status
from parcelpulse.registry import all_adapters
from parcelpulse.settings import settings

router = APIRouter(prefix="/admin/ops", tags=["ops"])


def require_ops_token(x_ops_token: str | None = Header(default=None)) -> None:
    expected = settings.ops_token
    if not expected:
        return  # dev mode
    if x_ops_token != expected:
        raise HTTPException(status_code=401, detail="invalid ops token")


@router.get("/metrics", dependencies=[Depends(require_ops_token)])
async def metrics(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sources = await source_status(all_adapters(), session)

    ingest_by_day = (
        await session.execute(
            text("""
                SELECT
                    date_trunc('day', ingested_at AT TIME ZONE 'UTC')::date::text AS day,
                    source,
                    count(*)::int AS events
                FROM events
                WHERE ingested_at >= now() - interval '7 days'
                GROUP BY 1, 2
                ORDER BY 1, 2
            """)
        )
    ).mappings().all()

    cost_by_day = (
        await session.execute(
            text("""
                SELECT
                    date_trunc('day', created_at AT TIME ZONE 'UTC')::date::text AS day,
                    tier,
                    round(sum(cost_usd)::numeric, 4)::float AS cost_usd
                FROM classifier_cache
                WHERE created_at >= now() - interval '7 days'
                GROUP BY 1, 2
                ORDER BY 1, 2
            """)
        )
    ).mappings().all()

    today = datetime.now(UTC).date()
    cost_today = (
        await session.execute(
            text("""
                SELECT round(coalesce(sum(cost_usd), 0)::numeric, 4)::float
                FROM classifier_cache
                WHERE created_at >= :d
                  AND created_at < :d + interval '1 day'
            """),
            {"d": today},
        )
    ).scalar_one()

    return {
        "sources": sources,
        "ingest_by_day": [dict(r) for r in ingest_by_day],
        "cost_by_day": [dict(r) for r in cost_by_day],
        "cost_today_usd": cost_today,
        "cost_cap_usd": settings.daily_llm_cost_cap_usd,
    }
