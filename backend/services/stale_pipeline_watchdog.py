"""
Stale-pipeline watchdog.

Pipelines run as FastAPI BackgroundTasks. If the Fly machine is killed
mid-run (e.g. by a redeploy), the running task vanishes silently: no Python
exception is raised, so `_run_pipeline`'s `except` block never fires, the
story remains in whatever non-terminal status the per-node writer last set,
and `error_message` stays NULL. From the user's side it looks frozen forever.

This module scans for stories whose `updated_at` timestamp is older than the
staleness threshold while still in a non-terminal status, and marks them
FAILED with a clear message. It runs once at FastAPI startup (catching
zombies from the previous machine generation) and then every
WATCHDOG_INTERVAL_SECONDS thereafter.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import update

from backend.db.database import AsyncSessionLocal
from backend.models.story import StoryORM, StoryStatus

log = structlog.get_logger(__name__)

STALE_THRESHOLD_MINUTES = 30
WATCHDOG_INTERVAL_SECONDS = 300

_TERMINAL_STATUSES: tuple[str, ...] = (
    StoryStatus.COMPLETED.value,
    StoryStatus.FAILED.value,
)

_STALE_MESSAGE = (
    "Pipeline was interrupted (likely by a backend restart) before completing. "
    "Please regenerate."
)


async def mark_stale_pipelines_failed() -> int:
    """Flip non-terminal stories with stale updated_at to FAILED. Returns row count."""
    threshold = datetime.now(timezone.utc) - timedelta(minutes=STALE_THRESHOLD_MINUTES)
    async with AsyncSessionLocal() as session:
        stmt = (
            update(StoryORM)
            .where(
                StoryORM.status.not_in(_TERMINAL_STATUSES),
                StoryORM.updated_at < threshold,
            )
            .values(
                status=StoryStatus.FAILED.value,
                error_message=_STALE_MESSAGE,
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        affected = result.rowcount or 0
    if affected:
        log.warning("watchdog.marked_stale_failed", count=affected)
    return affected


async def run_watchdog_loop() -> None:
    """Run mark_stale_pipelines_failed in a loop until cancelled."""
    while True:
        try:
            await mark_stale_pipelines_failed()
        except Exception as exc:
            log.error("watchdog.loop_error", error=str(exc))
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
