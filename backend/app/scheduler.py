"""
In-process daily scheduler.

The pipeline is triggered by a single APScheduler cron job inside the
uvicorn process, so there is no external dependency (no Task Scheduler, no
cron, no second service to keep alive). Startup and shutdown are driven by
the FastAPI lifespan in server.py.

DAILY_RUN_TIMEZONE must be an IANA zone name ("Asia/Kolkata"), not a Windows
zone id ("India Standard Time") — APScheduler resolves it via zoneinfo and
raises ZoneInfoNotFoundError otherwise.
"""

import asyncio
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

_scheduler: AsyncIOScheduler | None = None


def _log(message: str) -> None:
    # Imported lazily: server imports this module, so a top-level import of
    # server here would be circular.
    from app.server import log_event

    log_event("scheduler", message)


async def _fire(run: Callable[[str], object]) -> None:
    _log(
        f"Daily run starting ({settings.daily_run_hour:02d}:"
        f"{settings.daily_run_minute:02d} {settings.daily_run_timezone})"
    )
    try:
        result = run("scheduled")
        if asyncio.iscoroutine(result):
            await result
    except Exception as e:  # noqa: BLE001 - a failed daily run must not kill the process
        _log(f"Scheduled run failed to start: {e}")


def start(run: Callable[[str], object]) -> AsyncIOScheduler | None:
    """Attach the daily job to the running event loop. No-op if disabled."""
    global _scheduler

    if not settings.daily_run_enabled:
        _log("Daily scheduling disabled (DAILY_RUN_ENABLED=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler(timezone=settings.daily_run_timezone)
    scheduler.add_job(
        _fire,
        trigger=CronTrigger(
            hour=settings.daily_run_hour,
            minute=settings.daily_run_minute,
            timezone=settings.daily_run_timezone,
        ),
        args=[run],
        id="daily_reel",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    _scheduler = scheduler

    next_run = scheduler.get_job("daily_reel").next_run_time
    _log(
        f"Daily schedule armed: {settings.daily_run_hour:02d}:"
        f"{settings.daily_run_minute:02d} {settings.daily_run_timezone} "
        f"(next {next_run})"
    )
    return scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def describe() -> dict:
    """Schedule state for the dashboard."""
    next_run = None
    if _scheduler is not None:
        job = _scheduler.get_job("daily_reel")
        next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        "enabled": settings.daily_run_enabled,
        "at": f"{settings.daily_run_hour:02d}:{settings.daily_run_minute:02d}",
        "timezone": settings.daily_run_timezone,
        "next_run": next_run,
    }
