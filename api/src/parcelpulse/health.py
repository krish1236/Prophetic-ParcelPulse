"""Per-source ingestion lag computation surfaced by GET /health.

For every registered adapter we look up the latest `events.ingested_at` for
its source. A source with no rows yet returns null lag; otherwise lag is
seconds since that last insert.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from parcelpulse.adapters.base import SourceAdapter


class SourceStatus(TypedDict):
    name: str
    last_ingested_at: str | None
    lag_seconds: int | None
    paused: bool


async def source_status(
    adapters: Sequence[SourceAdapter], session: AsyncSession
) -> list[SourceStatus]:
    if not adapters:
        return []
    names = [a.name for a in adapters]
    rows = (
        await session.execute(
            text(
                "SELECT source, max(ingested_at) AS last_ingested_at "
                "FROM events WHERE source = ANY(:names) GROUP BY source"
            ),
            {"names": names},
        )
    ).all()
    last_by_source: dict[str, datetime] = {r.source: r.last_ingested_at for r in rows}

    now = datetime.now(UTC)
    out: list[SourceStatus] = []
    for adapter in adapters:
        last = last_by_source.get(adapter.name)
        out.append(
            {
                "name": adapter.name,
                "last_ingested_at": last.isoformat() if last else None,
                "lag_seconds": int((now - last).total_seconds()) if last else None,
                "paused": False,
            }
        )
    return out
