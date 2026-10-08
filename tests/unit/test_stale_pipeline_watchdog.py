from datetime import datetime, timedelta, timezone
import uuid

import pytest

from backend.models.story import StoryORM, StoryStatus, StoryTone
from backend.models.research_session import ResearchSessionORM, ResearchSessionStatus
from backend.services import stale_pipeline_watchdog as watchdog


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _story(status: StoryStatus, updated_at: datetime) -> StoryORM:
    return StoryORM(
        id=uuid.uuid4(),
        title=f"{status.value} story",
        topic="A sufficiently detailed topic for watchdog testing",
        status=status.value,
        tone=StoryTone.EXPLANATORY.value,
        created_at=updated_at,
        updated_at=updated_at,
    )


def _research_session(operation_started_at: datetime) -> ResearchSessionORM:
    return ResearchSessionORM(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Research session",
        report_markdown="",
        citations=[],
        turns=[
            {
                "prompt": "Research this topic",
                "created_at": operation_started_at.isoformat(),
                "status": ResearchSessionStatus.RUNNING.value,
                "completed_at": None,
                "error_message": None,
            }
        ],
        status=ResearchSessionStatus.RUNNING.value,
        active_operation="initial",
        pending_prompt="Research this topic",
        operation_started_at=operation_started_at,
        created_at=operation_started_at,
        updated_at=operation_started_at,
    )


@pytest.mark.asyncio
async def test_watchdog_keeps_angle_selection_open_before_six_hours(db_session, monkeypatch):
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    story = _story(
        StoryStatus.AWAITING_ANGLE_SELECTION,
        datetime.now(timezone.utc) - timedelta(hours=5, minutes=59),
    )
    db_session.add(story)
    await db_session.commit()

    affected = await watchdog.mark_stale_pipelines_failed()
    await db_session.refresh(story)

    assert affected == 0
    assert story.status == StoryStatus.AWAITING_ANGLE_SELECTION.value
    assert story.error_message is None


@pytest.mark.asyncio
async def test_watchdog_stops_angle_selection_after_six_hours(db_session, monkeypatch):
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    story = _story(
        StoryStatus.AWAITING_ANGLE_SELECTION,
        datetime.now(timezone.utc) - timedelta(hours=6, minutes=1),
    )
    db_session.add(story)
    await db_session.commit()

    affected = await watchdog.mark_stale_pipelines_failed()
    await db_session.refresh(story)

    assert affected == 1
    assert story.status == StoryStatus.ANGLE_SELECTION_EXPIRED.value
    assert story.error_message == watchdog.ANGLE_SELECTION_EXPIRED_MESSAGE


@pytest.mark.asyncio
async def test_watchdog_still_fails_active_stale_pipeline(db_session, monkeypatch):
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    story = _story(
        StoryStatus.SCRIPTING,
        datetime.now(timezone.utc) - timedelta(minutes=31),
    )
    db_session.add(story)
    await db_session.commit()

    affected = await watchdog.mark_stale_pipelines_failed()
    await db_session.refresh(story)

    assert affected == 1
    assert story.status == StoryStatus.FAILED.value
    assert "Pipeline was interrupted" in story.error_message


@pytest.mark.asyncio
async def test_watchdog_fails_stale_research_session(db_session, monkeypatch):
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    started_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    research_session = _research_session(started_at)
    db_session.add(research_session)
    await db_session.commit()

    affected = await watchdog.mark_stale_pipelines_failed()
    await db_session.refresh(research_session)

    assert affected == 1
    assert research_session.status == ResearchSessionStatus.FAILED.value
    assert research_session.active_operation is None
    assert research_session.pending_prompt is None
    assert research_session.error_message == watchdog._STALE_RESEARCH_MESSAGE
    assert research_session.turns[-1]["status"] == ResearchSessionStatus.FAILED.value


@pytest.mark.asyncio
async def test_watchdog_fails_stale_ideation_operation(db_session, monkeypatch):
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    started_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    story = _story(StoryStatus.IDEATING, started_at)
    story.ideation_operation_data = {
        "type": "chat",
        "status": "running",
        "message": "Find more angles",
        "started_at": started_at.isoformat(),
        "completed_at": None,
        "error_message": None,
    }
    story.ideation_chat_data = [
        {
            "role": "user",
            "content": "Find more angles",
            "created_at": started_at.isoformat(),
            "status": "running",
        }
    ]
    db_session.add(story)
    await db_session.commit()

    affected = await watchdog.mark_stale_pipelines_failed()
    await db_session.refresh(story)

    assert affected == 1
    assert story.status == StoryStatus.IDEATING.value
    assert story.ideation_operation_data["status"] == "failed"
    assert story.ideation_operation_data["error_message"] == watchdog._STALE_IDEATION_MESSAGE
    assert story.ideation_chat_data[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_watchdog_keeps_script_generation_inside_extended_window(db_session, monkeypatch):
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    started_at = datetime.now(timezone.utc) - timedelta(minutes=45)
    story = _story(StoryStatus.IDEATING, started_at)
    story.ideation_operation_data = {
        "type": "script_generation",
        "status": "running",
        "message": "Generating the final script.",
        "started_at": started_at.isoformat(),
        "last_heartbeat_at": started_at.isoformat(),
        "completed_at": None,
        "error_message": None,
    }
    db_session.add(story)
    await db_session.commit()

    affected = await watchdog.mark_stale_pipelines_failed()
    await db_session.refresh(story)

    assert affected == 0
    assert story.status == StoryStatus.IDEATING.value
    assert story.ideation_operation_data["status"] == "running"


@pytest.mark.asyncio
async def test_watchdog_fails_script_generation_after_extended_window(db_session, monkeypatch):
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    started_at = datetime.now(timezone.utc) - timedelta(
        minutes=watchdog.SCRIPT_GENERATION_STALE_THRESHOLD_MINUTES + 1
    )
    story = _story(StoryStatus.IDEATING, started_at)
    story.ideation_operation_data = {
        "type": "script_generation",
        "status": "running",
        "message": "Generating the final script.",
        "started_at": started_at.isoformat(),
        "last_heartbeat_at": started_at.isoformat(),
        "completed_at": None,
        "error_message": None,
    }
    db_session.add(story)
    await db_session.commit()

    affected = await watchdog.mark_stale_pipelines_failed()
    await db_session.refresh(story)

    assert affected == 1
    assert story.status == StoryStatus.IDEATING.value
    assert story.ideation_operation_data["status"] == "failed"
    assert story.ideation_operation_data["error_message"] == watchdog._STALE_SCRIPT_GENERATION_MESSAGE
