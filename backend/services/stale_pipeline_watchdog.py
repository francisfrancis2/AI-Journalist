"""
Stale-pipeline watchdog.

Pipelines run as FastAPI BackgroundTasks. If the Fly machine is killed
mid-run (e.g. by a redeploy), the running task vanishes silently: no Python
exception is raised, so `_run_pipeline`'s `except` block never fires, the
story remains in whatever non-terminal status the per-node writer last set,
and `error_message` stays NULL. From the user's side it looks frozen forever.

This module scans for active pipeline stories whose `updated_at` timestamp is
older than the staleness threshold and marks them FAILED with a clear message.
Angle-selection pauses are different: the user may legitimately take time to
approve an angle, so they are allowed to sit for six hours before being marked
as stopped, not failed. It runs once at FastAPI startup (catching zombies from
the previous machine generation) and then every WATCHDOG_INTERVAL_SECONDS
thereafter.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update

from backend.db.database import AsyncSessionLocal
from backend.models.research_session import ResearchSessionORM, ResearchSessionStatus
from backend.models.story import StoryORM, StoryStatus

log = structlog.get_logger(__name__)

STALE_THRESHOLD_MINUTES = 30
SCRIPT_GENERATION_STALE_THRESHOLD_MINUTES = 180
ANGLE_SELECTION_TIMEOUT_HOURS = 6
WATCHDOG_INTERVAL_SECONDS = 300

_STALE_ACTIVE_STATUSES: tuple[str, ...] = (
    StoryStatus.PENDING.value,
    StoryStatus.RESEARCHING.value,
    StoryStatus.ANALYSING.value,
    StoryStatus.WRITING_STORYLINE.value,
    StoryStatus.EVALUATING.value,
    StoryStatus.SCRIPTING.value,
)

_STALE_MESSAGE = (
    "Pipeline was interrupted (likely by a backend restart) before completing. "
    "Please regenerate."
)
_STALE_RESEARCH_MESSAGE = (
    "Research was interrupted before completing. Please run the request again."
)
_STALE_IDEATION_MESSAGE = (
    "This ideation request was interrupted before completing. Please try again."
)
_STALE_SCRIPT_GENERATION_MESSAGE = (
    "Script generation was interrupted before completing. Please try again."
)
_SCRIPT_GENERATION_OPERATION = "script_generation"

ANGLE_SELECTION_EXPIRED_MESSAGE = (
    "Script writing was stopped, as no angle was approved to proceed."
)


def _parse_operation_started_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _operation_last_activity_at(operation: dict) -> datetime | None:
    return (
        _parse_operation_started_at(operation.get("last_heartbeat_at"))
        or _parse_operation_started_at(operation.get("started_at"))
    )


def _ideation_stale_threshold(now: datetime, operation: dict) -> datetime:
    if operation.get("type") == _SCRIPT_GENERATION_OPERATION:
        return now - timedelta(minutes=SCRIPT_GENERATION_STALE_THRESHOLD_MINUTES)
    return now - timedelta(minutes=STALE_THRESHOLD_MINUTES)


def _stale_ideation_error_message(operation: dict) -> str:
    if operation.get("type") == _SCRIPT_GENERATION_OPERATION:
        return _STALE_SCRIPT_GENERATION_MESSAGE
    return _STALE_IDEATION_MESSAGE


def _mark_latest_research_turn_failed(turns: object, error_message: str, completed_at: datetime) -> list:
    cleaned = [dict(item) for item in (turns or []) if isinstance(item, dict)]
    if not cleaned:
        return cleaned
    latest = dict(cleaned[-1])
    latest["status"] = ResearchSessionStatus.FAILED.value
    latest["completed_at"] = completed_at.isoformat()
    latest["error_message"] = error_message
    return [*cleaned[:-1], latest]


def _mark_latest_ideation_message_failed(chat_data: object, error_message: str, completed_at: datetime) -> list:
    history = [dict(item) for item in (chat_data or []) if isinstance(item, dict)]
    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        if item.get("role") == "user" and item.get("status") == "running":
            item["status"] = "failed"
            item["completed_at"] = completed_at.isoformat()
            item["error_message"] = error_message
            history[index] = item
            break
    return history


async def mark_stale_pipelines_failed() -> int:
    """Update stale pipeline records. Returns total affected row count."""
    now = datetime.now(timezone.utc)
    stale_pipeline_threshold = now - timedelta(minutes=STALE_THRESHOLD_MINUTES)
    angle_selection_threshold = now - timedelta(hours=ANGLE_SELECTION_TIMEOUT_HOURS)

    async with AsyncSessionLocal() as session:
        stale_pipeline_stmt = (
            update(StoryORM)
            .where(
                StoryORM.status.in_(_STALE_ACTIVE_STATUSES),
                StoryORM.updated_at < stale_pipeline_threshold,
            )
            .values(
                status=StoryStatus.FAILED.value,
                error_message=_STALE_MESSAGE,
            )
        )
        stale_pipeline_result = await session.execute(stale_pipeline_stmt)

        expired_angle_stmt = (
            update(StoryORM)
            .where(
                StoryORM.status == StoryStatus.AWAITING_ANGLE_SELECTION.value,
                StoryORM.updated_at < angle_selection_threshold,
            )
            .values(
                status=StoryStatus.ANGLE_SELECTION_EXPIRED.value,
                error_message=ANGLE_SELECTION_EXPIRED_MESSAGE,
            )
        )
        expired_angle_result = await session.execute(expired_angle_stmt)

        stale_research_result = await session.execute(
            select(ResearchSessionORM).where(
                ResearchSessionORM.status == ResearchSessionStatus.RUNNING.value,
                ResearchSessionORM.operation_started_at < stale_pipeline_threshold,
            )
        )
        stale_research_sessions = list(stale_research_result.scalars().all())
        for research_session in stale_research_sessions:
            research_session.status = ResearchSessionStatus.FAILED.value
            research_session.active_operation = None
            research_session.pending_prompt = None
            research_session.error_message = _STALE_RESEARCH_MESSAGE
            research_session.operation_completed_at = now
            research_session.turns = _mark_latest_research_turn_failed(
                research_session.turns,
                _STALE_RESEARCH_MESSAGE,
                now,
            )

        ideation_result = await session.execute(
            select(StoryORM).where(
                StoryORM.status == StoryStatus.IDEATING.value,
                StoryORM.ideation_operation_data.is_not(None),
            )
        )
        stale_ideation_count = 0
        for story in ideation_result.scalars().all():
            operation = story.ideation_operation_data
            if not isinstance(operation, dict) or operation.get("status") != "running":
                continue
            activity_at = _operation_last_activity_at(operation)
            stale_ideation_threshold = _ideation_stale_threshold(now, operation)
            if activity_at is not None and activity_at >= stale_ideation_threshold:
                continue
            error_message = _stale_ideation_error_message(operation)
            completed_operation = dict(operation)
            completed_operation["status"] = "failed"
            completed_operation["completed_at"] = now.isoformat()
            completed_operation["error_message"] = error_message
            story.ideation_operation_data = completed_operation
            story.ideation_chat_data = _mark_latest_ideation_message_failed(
                story.ideation_chat_data,
                error_message,
                now,
            )
            story.error_message = error_message
            stale_ideation_count += 1

        await session.commit()
        stale_pipeline_count = stale_pipeline_result.rowcount or 0
        expired_angle_count = expired_angle_result.rowcount or 0
        stale_research_count = len(stale_research_sessions)

    if stale_pipeline_count:
        log.warning("watchdog.marked_stale_failed", count=stale_pipeline_count)
    if stale_research_count:
        log.warning("watchdog.marked_stale_research_failed", count=stale_research_count)
    if stale_ideation_count:
        log.warning("watchdog.marked_stale_ideation_failed", count=stale_ideation_count)
    if expired_angle_count:
        log.info(
            "watchdog.marked_angle_selection_expired",
            count=expired_angle_count,
            timeout_hours=ANGLE_SELECTION_TIMEOUT_HOURS,
        )
    return stale_pipeline_count + expired_angle_count + stale_research_count + stale_ideation_count


async def run_watchdog_loop() -> None:
    """Run mark_stale_pipelines_failed in a loop until cancelled."""
    while True:
        try:
            await mark_stale_pipelines_failed()
        except Exception as exc:
            log.error("watchdog.loop_error", error=str(exc))
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
