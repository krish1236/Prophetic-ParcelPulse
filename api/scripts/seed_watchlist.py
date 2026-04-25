"""Seed the demo watchlist used for Phase 3+ engine demos.

Idempotent: re-running upserts the watchlist record and adds any missing
parcel links via ON CONFLICT DO NOTHING. Safe to re-run after data reloads.

Usage:
    python api/scripts/seed_watchlist.py
"""

import asyncio
from uuid import UUID

from sqlalchemy import text

from parcelpulse.db import SessionLocal

# Hardcoded so the watchlist has a stable id across fresh DBs and re-runs.
DEMO_WATCHLIST_ID = UUID("00000000-0000-0000-0000-000000000001")
DEMO_WORKSPACE_ID = UUID("00000000-0000-0000-0000-0000000000a1")

DEMO_DEAL_THESIS = (
    "Townhomes 8-12 du/ac, must clear FEMA Zone X. Looking for infill or "
    "small-multifamily lots in central Portland; flag any change to zoning, "
    "permits, ownership, flood designation, or comparable sales."
)

# Picked deterministically from the loaded Multnomah parcels: 10 lots in central
# Portland, ~1.8-2.0 acres, mix of residential (R5/R2.5/RM2/RM3) and commercial
# mixed-use (CX) zoning. Real addresses, real geometry, large enough to be
# realistic infill/small-multifamily targets.
DEMO_PARCEL_APNS: list[str] = [
    "1S1E03CD  -00800",  # 2065 S RIVER PKWY (CX, 1.99ac)
    "1N1E35AB  -07101",  # 1510 NE MULTNOMAH ST (CX, 1.98ac)
    "1N1E23DB  -15600",  # 4013 NE 18TH AVE (R5, 1.96ac)
    "1N1E16DA  -16000",  # 1515 N AINSWORTH ST (RM3, 1.93ac)
    "1N2E31DD  -08100",  # 90 WI/ SE 57TH AVE (RM2, 1.88ac)
    "1S1E03CB  -00800",  # 200 SW MARKET ST (CX, 1.86ac)
    "1N1E22DD  -12700",  # 3719-3823 NE GARFIELD AVE (RM2, 1.84ac)
    "1N1E26CD  -12800",  # 1200 NE BROADWAY (CX, 1.82ac)
    "1S2E06BC  -12900",  # 4219 SE SALMON ST (R2.5, 1.81ac)
    "1N1E34AA  -03001",  # 325 NE HASSALO ST (CX, 1.8ac)
]
MULTNOMAH_FIPS = "41051"


async def seed() -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO watchlists (watchlist_id, workspace_id, name, "
                "deal_thesis, thesis_version) "
                "VALUES (:wl, :ws, 'Demo: central Portland infill', :thesis, 1) "
                "ON CONFLICT (watchlist_id) DO UPDATE SET "
                "deal_thesis = EXCLUDED.deal_thesis"
            ),
            {
                "wl": str(DEMO_WATCHLIST_ID),
                "ws": str(DEMO_WORKSPACE_ID),
                "thesis": DEMO_DEAL_THESIS,
            },
        )
        result = await session.execute(
            text(
                "INSERT INTO watched_parcels (watchlist_id, parcel_id) "
                "SELECT :wl, parcel_id "
                "FROM parcels "
                "WHERE county_fips = :fips AND apn = ANY(:apns) "
                "ON CONFLICT (watchlist_id, parcel_id) DO NOTHING "
                "RETURNING parcel_id"
            ),
            {
                "wl": str(DEMO_WATCHLIST_ID),
                "fips": MULTNOMAH_FIPS,
                "apns": DEMO_PARCEL_APNS,
            },
        )
        added = len(result.fetchall())
        await session.commit()

        total = (
            await session.execute(
                text(
                    "SELECT count(*) FROM watched_parcels WHERE watchlist_id = :wl"
                ),
                {"wl": str(DEMO_WATCHLIST_ID)},
            )
        ).scalar_one()
        missing = len(DEMO_PARCEL_APNS) - total
        print(
            f"watchlist={DEMO_WATCHLIST_ID} added_now={added} "
            f"total_watched={total} missing_apns={missing}"
        )
        if missing > 0:
            print("  (run scripts/load_parcels.py first if missing > 0)")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
