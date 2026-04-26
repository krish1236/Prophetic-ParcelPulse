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
from parcelpulse.circuit_breaker import is_paused, record_failure, record_success
from parcelpulse.ingest import insert_events
from parcelpulse.materiality.classify import classify_events
from parcelpulse.registry import all_adapters

log = logging.getLogger(__name__)


async def run_adapter_once(adapter: SourceAdapter) -> tuple[int, int, int]:
    """Pull → ingest → classify for one adapter. Returns (fetched, inserted, alerted).

    Skips the pull entirely if the source's circuit breaker is open. A
    successful fetch clears any partial-failure count; a fetch exception
    increments the count and may trip the breaker.
    """
    if await is_paused(adapter.name):
        log.warning("adapter=%s skipped: circuit breaker open", adapter.name)
        return 0, 0, 0
    try:
        events = await adapter.fetch()
    except Exception:
        await record_failure(adapter.name)
        log.exception("adapter=%s fetch failed", adapter.name)
        return 0, 0, 0
    await record_success(adapter.name)
    try:
        new_ids = await insert_events(events)
    except Exception:
        log.exception("adapter=%s insert failed (fetched=%d)", adapter.name, len(events))
        return len(events), 0, 0
    inserted = len(new_ids)
    alerted = 0
    if new_ids:
        try:
            alerted = await classify_events(new_ids)
        except Exception:
            log.exception("adapter=%s classify failed (inserted=%d)", adapter.name, inserted)
    log.info(
        "adapter=%s fetched=%d inserted=%d alerted=%d",
        adapter.name,
        len(events),
        inserted,
        alerted,
    )
    return len(events), inserted, alerted


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
    from parcelpulse.observability import configure_logging

    configure_logging()
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
