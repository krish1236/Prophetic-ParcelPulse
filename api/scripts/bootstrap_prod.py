"""Idempotent prod bootstrap. Runs at container start on Railway.

  1. `alembic upgrade head` — always (no-op when at head, fast)
  2. If parcels table is empty: load Multnomah parcels (~10min) + seed watchlist
     + seed fixture alerts. Skipped on every restart after first deploy.

Concurrency-safe: api and worker services share this entrypoint and may both
start cold. Each step uses UPSERT semantics, so a race just duplicates work,
not data.

Run order (matches the Dockerfile ENTRYPOINT):
    docker run ... python scripts/bootstrap_prod.py && exec uvicorn ...
"""

import asyncio
import subprocess
import sys

from sqlalchemy import text

from parcelpulse.db import SessionLocal


def run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)


async def parcels_already_loaded() -> bool:
    async with SessionLocal() as session:
        count = (
            await session.execute(text("SELECT count(*) FROM parcels"))
        ).scalar_one()
    print(f"[bootstrap] parcels in DB: {count}", flush=True)
    return count > 0


async def main() -> None:
    print("[bootstrap] running migrations...", flush=True)
    run(["alembic", "upgrade", "head"])

    # Heavy: only on a truly empty DB.
    if await parcels_already_loaded():
        print("[bootstrap] parcels already loaded; skipping load_parcels.", flush=True)
    else:
        print("[bootstrap] empty DB — loading ~284k parcels (~10 min)...", flush=True)
        run(["python", "scripts/load_parcels.py"])

    # Cheap + idempotent (ON CONFLICT DO UPDATE) — run every start so the demo
    # watchlist and fixture alerts always exist, even if a prior bootstrap
    # half-completed or someone wiped the data.
    run(["python", "scripts/seed_watchlist.py"])
    run(["python", "scripts/seed_fixture_alerts.py"])
    print("[bootstrap] complete.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
