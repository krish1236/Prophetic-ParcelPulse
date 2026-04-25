"""Process that runs every registered scheduled adapter on its cron expression.

Run as: `parcelpulse-scheduler` (console script) or `python -m parcelpulse.workers.scheduler`.

On startup the scheduler invokes every registered adapter once immediately so
the first batch of events lands without waiting a full cron cycle, then hands
off to APScheduler for the recurring runs.
"""

import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from parcelpulse.adapters.base import SourceAdapter
from parcelpulse.adapters.multco_permits import MultcoPermitsAdapter
from parcelpulse.ingest import insert_events

log = logging.getLogger(__name__)


def all_adapters() -> list[SourceAdapter]:
    return [MultcoPermitsAdapter()]


async def run_adapter_once(adapter: SourceAdapter) -> tuple[int, int]:
    """Pull from one adapter and ingest. Returns (fetched, newly_inserted)."""
    try:
        events = await adapter.fetch()
    except Exception:
        log.exception("adapter=%s fetch failed", adapter.name)
        return 0, 0
    try:
        inserted = await insert_events(events)
    except Exception:
        log.exception("adapter=%s insert failed (fetched=%d)", adapter.name, len(events))
        return len(events), 0
    log.info(
        "adapter=%s fetched=%d inserted=%d", adapter.name, len(events), inserted
    )
    return len(events), inserted


async def run_scheduler() -> None:
    adapters = all_adapters()

    # Initial pull so the events table is non-empty without waiting a cron tick.
    for adapter in adapters:
        await run_adapter_once(adapter)

    scheduler = AsyncIOScheduler()
    for adapter in adapters:
        if adapter.mode != "scheduled" or not adapter.schedule_expr:
            continue
        scheduler.add_job(
            run_adapter_once,
            trigger=CronTrigger.from_crontab(adapter.schedule_expr),
            args=[adapter],
            id=f"adapter-{adapter.name}",
            misfire_grace_time=60,
            coalesce=True,
            max_instances=1,
        )
        log.info("scheduled adapter=%s cron=%s", adapter.name, adapter.schedule_expr)
    scheduler.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    log.info("scheduler running; ctrl-c to stop")
    await stop_event.wait()
    log.info("scheduler stopping")
    scheduler.shutdown()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
