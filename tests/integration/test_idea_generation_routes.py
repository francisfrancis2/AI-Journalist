"""API lifecycle tests for the persisted Idea Generator workspace."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy import select

from backend.models.idea_generation import (
    GeneratedIdeaORM,
    IdeaGenerationRunORM,
    IdeaSourceORM,
)
from backend.models.research_session import ResearchSessionORM
from backend.models.story import StoryORM
from backend.models.user import UserORM


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_is_idempotent_and_discloses_google_trends_gap(api_client, monkeypatch) -> None:
    task = AsyncMock()
    monkeypatch.setattr("backend.api.routes.idea_generations._run_generation", task)
    headers = {"Idempotency-Key": "idea-test-key"}

    first = await api_client.post(
        "/api/v1/idea-generations",
        json={"format": "documentary", "previous_run_id": None},
        headers=headers,
    )
    assert first.status_code == 202
    body = first.json()
    assert body["status"] == "queued"
    assert body["coverage_level"] == "partial"
    assert "google_trends_not_configured" in body["coverage_reasons"]
    assert body["provider_statuses"]["google_trends"]["status"] == "not_configured"

    second = await api_client.post(
        "/api/v1/idea-generations",
        json={"format": "documentary", "previous_run_id": None},
        headers=headers,
    )
    assert second.status_code == 202
    assert second.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_one_active_run_is_reused_for_repeated_lucky_clicks(api_client, monkeypatch) -> None:
    monkeypatch.setattr("backend.api.routes.idea_generations._run_generation", AsyncMock())
    first = await api_client.post(
        "/api/v1/idea-generations",
        json={"format": "documentary"},
        headers={"Idempotency-Key": "first-click"},
    )
    second = await api_client.post(
        "/api/v1/idea-generations",
        json={"format": "expert_interview"},
        headers={"Idempotency-Key": "second-click"},
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["format"] == "documentary"


@pytest.mark.asyncio
async def test_generation_deadline_records_terminal_failure(api_client, db_session, monkeypatch) -> None:
    from backend.api.routes import idea_generations as routes

    user = (await db_session.execute(select(UserORM))).scalars().one()
    run = IdeaGenerationRunORM(
        user_id=user.id,
        idempotency_key=str(uuid.uuid4()),
        request_hash="d" * 64,
        format="documentary",
        status="queued",
        stage="queued",
        stage_progress=0,
        coverage_level="partial",
        coverage_reasons=[],
        provider_statuses={},
        candidate_metrics={},
        usage_metrics={},
    )
    db_session.add(run)
    await db_session.commit()

    class SlowAgent:
        async def generate(self, idea_format, *, on_stage=None):
            await asyncio.sleep(1)

    monkeypatch.setattr(routes, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    monkeypatch.setattr(routes, "_get_agent", lambda: SlowAgent())
    monkeypatch.setattr(routes.settings, "idea_generator_total_timeout_seconds", 0.01)

    await routes._run_generation(run.id)
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.stage == "failed"
    assert run.stage_progress == 100
    assert run.error_code == "generation_timed_out"
    assert "five-minute limit" in run.error_message


def _leased_run(user_id: uuid.UUID, *, lease_expires_at: datetime, attempt_count: int) -> IdeaGenerationRunORM:
    now = datetime.now(timezone.utc)
    return IdeaGenerationRunORM(
        user_id=user_id,
        idempotency_key=str(uuid.uuid4()),
        request_hash="l" * 64,
        format="documentary",
        status="running",
        stage="synthesizing_ideas",
        stage_progress=65,
        coverage_level="partial",
        coverage_reasons=[],
        provider_statuses={},
        candidate_metrics={},
        usage_metrics={},
        worker_id="worker-v1",
        heartbeat_at=now,
        lease_expires_at=lease_expires_at,
        attempt_count=attempt_count,
        started_at=now,
    )


@pytest.mark.asyncio
async def test_other_backend_startup_preserves_live_idea_worker_lease(
    db_session,
    monkeypatch,
) -> None:
    from backend.api.routes import idea_generations as routes

    run = _leased_run(
        uuid.uuid4(),
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        attempt_count=1,
    )
    db_session.add(run)
    await db_session.commit()
    scheduled_ids: list[uuid.UUID] = []

    monkeypatch.setattr(routes, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    monkeypatch.setattr(routes, "_schedule_generation", lambda run_id: scheduled_ids.append(run_id) or True)

    scheduled = await routes.recover_expired_idea_generations()
    await db_session.refresh(run)

    assert scheduled == 0
    assert scheduled_ids == []
    assert run.status == "running"
    assert run.worker_id == "worker-v1"
    assert run.error_code is None


@pytest.mark.asyncio
async def test_expired_idea_worker_lease_is_recovered_by_one_new_worker(
    db_session,
    monkeypatch,
) -> None:
    from backend.api.routes import idea_generations as routes

    run = _leased_run(
        uuid.uuid4(),
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        attempt_count=1,
    )
    db_session.add(run)
    await db_session.commit()
    original_started_at = run.started_at
    scheduled_ids: list[uuid.UUID] = []

    monkeypatch.setattr(routes, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    monkeypatch.setattr(routes, "_WORKER_ID", "worker-v2")
    monkeypatch.setattr(routes, "_schedule_generation", lambda run_id: scheduled_ids.append(run_id) or True)

    scheduled = await routes.recover_expired_idea_generations()
    claim = await routes._claim_generation_run(run.id)
    second_claim = await routes._claim_generation_run(run.id)
    await db_session.refresh(run)

    assert scheduled == 1
    assert scheduled_ids == [run.id]
    assert claim is not None
    assert claim[:2] == (routes.IdeaFormat.DOCUMENTARY, 2)
    assert second_claim is None
    assert run.status == "running"
    assert run.worker_id == "worker-v2"
    assert run.attempt_count == 2
    assert run.started_at.replace(tzinfo=timezone.utc) == original_started_at


@pytest.mark.asyncio
async def test_expired_idea_run_fails_only_after_recovery_attempt_is_exhausted(
    db_session,
    monkeypatch,
) -> None:
    from backend.api.routes import idea_generations as routes

    run = _leased_run(
        uuid.uuid4(),
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        attempt_count=routes.settings.idea_generator_max_worker_attempts,
    )
    db_session.add(run)
    await db_session.commit()

    monkeypatch.setattr(routes, "AsyncSessionLocal", lambda: _SessionContext(db_session))
    monkeypatch.setattr(routes, "_schedule_generation", lambda run_id: True)

    scheduled = await routes.recover_expired_idea_generations()
    await db_session.refresh(run)

    assert scheduled == 0
    assert run.status == "failed"
    assert run.error_code == "interrupted"
    assert run.worker_id is None
    assert run.lease_expires_at is None


async def _persist_idea(db_session, *, idea_format: str) -> GeneratedIdeaORM:
    user = (await db_session.execute(select(UserORM))).scalars().one()
    run = IdeaGenerationRunORM(
        user_id=user.id,
        idempotency_key=str(uuid.uuid4()),
        request_hash="a" * 64,
        format=idea_format,
        status="completed",
        stage="completed",
        stage_progress=100,
        coverage_level="partial",
        coverage_reasons=["google_trends_not_configured"],
        provider_statuses={},
        candidate_metrics={},
        usage_metrics={},
    )
    db_session.add(run)
    await db_session.flush()
    source = IdeaSourceORM(
        run_id=run.id,
        url="https://example.ae/current-report",
        domain="example.ae",
        title="Current UAE business report",
        excerpt="Named current evidence about a UAE business development.",
        source_type="news_api",
        credibility="high",
        is_uae_relevant=True,
        is_primary=False,
        content_hash="b" * 64,
        raw_metadata={},
    )
    idea = GeneratedIdeaORM(
        run_id=run.id,
        rank=1,
        format=idea_format,
        sector="Technology",
        title="The UAE business system changing in plain sight",
        premise="Follow the people and companies making a measurable operating shift across the UAE.",
        why_now="A new investment cycle makes the shift timely and visible.",
        uae_relevance="The development is taking place in named UAE businesses and markets.",
        central_tension="Fast adoption depends on economics access and workforce readiness.",
        target_audience="Business viewers",
        business_significance="The outcome could change operating costs and regional competition.",
        format_details={"access_path": "companies and operators"},
        score_breakdown={"evidence_quality": 5},
        score=80,
        strength="strong",
        coverage={"level": "partial"},
        verification_gaps=[],
        sources=[source],
    )
    db_session.add(idea)
    await db_session.commit()
    return idea


@pytest.mark.asyncio
async def test_expert_interview_handoff_is_research_only(api_client, db_session) -> None:
    idea = await _persist_idea(db_session, idea_format="expert_interview")
    story_preview = await api_client.get(
        f"/api/v1/idea-generations/ideas/{idea.id}/handoff",
        params={"target": "story"},
    )
    research_preview = await api_client.get(
        f"/api/v1/idea-generations/ideas/{idea.id}/handoff",
        params={"target": "research"},
    )
    assert story_preview.status_code == 200
    assert story_preview.json()["allowed"] is False
    assert research_preview.json()["allowed"] is True


@pytest.mark.asyncio
async def test_confirmed_handoffs_copy_evidence_without_running_during_preview(
    api_client, db_session, monkeypatch
) -> None:
    idea = await _persist_idea(db_session, idea_format="documentary")
    story_task = AsyncMock()
    research_task = AsyncMock()
    monkeypatch.setattr("backend.api.routes.stories._run_ideation_operation", story_task)
    monkeypatch.setattr("backend.api.routes.research_sessions._run_initial_research_session", research_task)

    preview = await api_client.get(
        f"/api/v1/idea-generations/ideas/{idea.id}/handoff",
        params={"target": "story"},
    )
    assert preview.status_code == 200
    assert preview.json()["inherited_source_count"] == 1
    story_task.assert_not_awaited()
    research_task.assert_not_awaited()

    story_response = await api_client.post(
        "/api/v1/stories/ideation",
        json={"prompt": preview.json()["prompt"], "origin_idea_id": str(idea.id)},
    )
    assert story_response.status_code == 201
    assert story_response.json()["story"]["origin_idea_id"] == str(idea.id)
    story_task.assert_awaited_once()
    story = (await db_session.execute(select(StoryORM))).scalars().one()
    assert story.research_mode == "seeded"
    assert len(story.seed_research_data["sources"]) == 1

    research_response = await api_client.post(
        "/api/v1/research/sessions",
        json={"prompt": preview.json()["prompt"], "origin_idea_id": str(idea.id)},
    )
    assert research_response.status_code == 201
    assert research_response.json()["origin_idea_id"] == str(idea.id)
    research_task.assert_awaited_once()
    session = (await db_session.execute(select(ResearchSessionORM))).scalars().one()
    assert len(session.seed_evidence_data["sources"]) == 1


def _completed_run(user_id: uuid.UUID, *, fmt: str = "documentary") -> IdeaGenerationRunORM:
    now = datetime.now(timezone.utc)
    return IdeaGenerationRunORM(
        user_id=user_id,
        idempotency_key=str(uuid.uuid4()),
        request_hash="c" * 64,
        format=fmt,
        status="completed",
        stage="completed",
        stage_progress=100,
        coverage_level="partial",
        coverage_reasons=[],
        provider_statuses={},
        candidate_metrics={},
        usage_metrics={},
        started_at=now,
        completed_at=now,
    )


@pytest.mark.asyncio
async def test_admin_sees_every_users_idea_runs_attributed_by_owner(
    api_client, db_session
) -> None:
    """Idea history follows the research-session rule: admins see all, attributed.

    Before this, the listing was unconditionally scoped to the caller, so idea
    generation was the one workflow an admin had no visibility into.
    """
    admin = (await db_session.execute(select(UserORM).where(UserORM.is_admin.is_(True)))).scalars().first()
    other = UserORM(
        id=uuid.uuid4(),
        email="other@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
        is_admin=False,
    )
    db_session.add(other)
    db_session.add(_completed_run(admin.id))
    db_session.add(_completed_run(other.id, fmt="expert_interview"))
    await db_session.commit()

    response = await api_client.get("/api/v1/idea-generations")
    assert response.status_code == 200
    runs = response.json()
    emails = {run["owner_email"] for run in runs}
    assert emails == {admin.email, "other@example.com"}, "admin must see both users' runs"


@pytest.mark.asyncio
async def test_non_admin_sees_only_their_own_runs_without_attribution(
    api_client, db_session
) -> None:
    caller = (await db_session.execute(select(UserORM).where(UserORM.is_admin.is_(True)))).scalars().first()
    other = UserORM(
        id=uuid.uuid4(),
        email="stranger@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
        is_admin=False,
    )
    db_session.add(other)
    db_session.add(_completed_run(caller.id))
    db_session.add(_completed_run(other.id))
    await db_session.commit()

    # The fixture's user is the one the request authenticates as, so dropping
    # its admin flag exercises the non-admin branch without a second client.
    caller.is_admin = False
    await db_session.commit()

    response = await api_client.get("/api/v1/idea-generations")
    assert response.status_code == 200
    runs = response.json()
    assert len(runs) == 1, "a non-admin must not see another user's runs"
    assert runs[0]["owner_email"] is None, "attribution is for admins only"
