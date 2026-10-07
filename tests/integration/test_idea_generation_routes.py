"""API lifecycle tests for the persisted Idea Generator workspace."""

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
