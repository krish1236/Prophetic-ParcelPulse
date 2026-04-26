"""Tier 0 — cheap rule-based + spatial-join pre-filter.

Runs in pure SQL on every ingested event. Drops events that:
  * have an event_type not in the materiality taxonomy
  * have no geometry (can't be spatially attributed)
  * don't fall within `proximity_m` of any watched parcel

Outputs zero or more `Candidate(event_id, watchlist_id, parcel_id)` tuples
that flow into Tier 1 (Haiku materiality screen).

Sized to drop ~70% of incoming events per architecture §6.1.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Materiality taxonomy. Events outside this set are dropped at Tier 0.
# Matches vision §7 axes: zoning / flood / permit / ownership / market.
MATERIAL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        # Permits (Phase 2)
        "permit.new",
        "permit.alteration",
        "permit.demolition",
        "permit.addition",
        "permit.repair",
        "permit.other",
        # Future axes (Phase 8)
        "zoning.amendment",
        "zoning.overlay",
        "flood.lomr",
        "flood.loma",
        "ownership.deed",
        "ownership.listing",
        "market.comp",
    }
)


@dataclass(frozen=True)
class Candidate:
    event_id: UUID
    watchlist_id: UUID
    parcel_id: UUID


_SPATIAL_JOIN_SQL = text("""
    SELECT wp.watchlist_id, wp.parcel_id
    FROM events e
    JOIN watched_parcels wp ON TRUE
    JOIN parcels p ON p.parcel_id = wp.parcel_id
    WHERE e.event_id = :event_id
      AND e.geometry IS NOT NULL
      AND e.event_type = ANY(:material_types)
      AND ST_DWithin(p.geom::geography, e.geometry::geography, :proximity_m)
""")


async def find_candidates(
    event_id: UUID,
    session: AsyncSession,
    proximity_m: float = 152.4,
) -> list[Candidate]:
    """For an ingested event, return the (watchlist, parcel) pairs that
    spatially attribute to it. `proximity_m` defaults to ~500 ft so a permit
    point near (but not strictly inside) a parcel still triggers Tier 1.
    """
    rows = await session.execute(
        _SPATIAL_JOIN_SQL,
        {
            "event_id": str(event_id),
            "material_types": list(MATERIAL_EVENT_TYPES),
            "proximity_m": proximity_m,
        },
    )
    return [
        Candidate(event_id=event_id, watchlist_id=row[0], parcel_id=row[1])
        for row in rows.all()
    ]
