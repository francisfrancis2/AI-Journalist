"""
Integration tests for the FastAPI REST API.
Uses an in-memory SQLite database via the db_session fixture from conftest.
The LangGraph pipeline is NOT invoked in these tests — we test the API layer only.
"""

import uuid

import pytest

from backend.models.benchmark import BIReferenceDocORM
from backend.models.story import StoryORM, StoryStatus, StoryTone


# ── Health check ──────────────────────────────────────────────────────────────

class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, api_client):
        response = await api_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


# ── Stories CRUD ──────────────────────────────────────────────────────────────

class TestStoriesCreate:
    @pytest.mark.asyncio
    async def test_create_story_returns_202(self, api_client, mocker):
        # Mock the background task so the pipeline doesn't actually run
        mocker.patch("backend.api.routes.stories._run_pipeline")

        payload = {
            "topic": "How NVIDIA became the world's most valuable chip company",
            "tone": "investigative",
        }
        response = await api_client.post("/api/v1/stories/", json=payload)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == StoryStatus.PENDING
        assert data["tone"] == StoryTone.INVESTIGATIVE
        assert data["target_duration_minutes"] == 12
        assert data["target_audience"] is None
        assert data["script_audit_data"] is None
        assert uuid.UUID(data["id"])  # valid UUID

    @pytest.mark.asyncio
    async def test_create_story_uses_topic_as_default_title(self, api_client, mocker):
        mocker.patch("backend.api.routes.stories._run_pipeline")
        payload = {"topic": "Exactly ten chars topic here", "tone": "explanatory"}
        response = await api_client.post("/api/v1/stories/", json=payload)
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_create_story_topic_too_short(self, api_client):
        payload = {"topic": "Short", "tone": "explanatory"}
        response = await api_client.post("/api/v1/stories/", json=payload)
        assert response.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_create_story_with_custom_title(self, api_client, mocker):
        mocker.patch("backend.api.routes.stories._run_pipeline")
        payload = {
            "topic": "A long enough topic to pass validation",
            "title": "My Custom Title",
            "tone": "narrative",
        }
        response = await api_client.post("/api/v1/stories/", json=payload)
        assert response.status_code == 202
        assert response.json()["title"] == "My Custom Title"

    @pytest.mark.asyncio
    async def test_create_story_accepts_script_targeting_options(self, api_client, mocker):
        mocker.patch("backend.api.routes.stories._run_pipeline")
        payload = {
            "topic": "A long enough topic to pass validation for targeting",
            "tone": "explanatory",
            "target_duration_minutes": 15,
            "target_audience": "Founders and business viewers",
        }
        response = await api_client.post("/api/v1/stories/", json=payload)
        assert response.status_code == 202
        data = response.json()
        assert data["target_duration_minutes"] == 15
        assert data["target_audience"] == "Founders and business viewers"


class TestStoriesList:
    @pytest.mark.asyncio
    async def test_list_empty(self, api_client):
        response = await api_client.get("/api/v1/stories/")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_list_returns_created_stories(self, api_client, mocker):
        mocker.patch("backend.api.routes.stories._run_pipeline")
        topic = "A sufficiently long research topic for testing"
        await api_client.post("/api/v1/stories/", json={"topic": topic, "tone": "explanatory"})

        response = await api_client.get("/api/v1/stories/")
        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.asyncio
    async def test_list_respects_limit(self, api_client, mocker):
        mocker.patch("backend.api.routes.stories._run_pipeline")
        topic = "A sufficiently long research topic for testing"
        for _ in range(5):
            await api_client.post("/api/v1/stories/", json={"topic": topic, "tone": "explanatory"})

        response = await api_client.get("/api/v1/stories/?limit=3")
        assert response.status_code == 200
        assert len(response.json()) == 3


class TestStoriesGet:
    @pytest.mark.asyncio
    async def test_get_existing_story(self, api_client, mocker):
        mocker.patch("backend.api.routes.stories._run_pipeline")
        create_resp = await api_client.post(
            "/api/v1/stories/",
            json={"topic": "A valid topic for integration testing", "tone": "trend"},
        )
        story_id = create_resp.json()["id"]

        get_resp = await api_client.get(f"/api/v1/stories/{story_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == story_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_story(self, api_client):
        fake_id = str(uuid.uuid4())
        response = await api_client.get(f"/api/v1/stories/{fake_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_script_before_completion(self, api_client, mocker):
        mocker.patch("backend.api.routes.stories._run_pipeline")
        create_resp = await api_client.post(
            "/api/v1/stories/",
            json={"topic": "A valid topic for integration testing", "tone": "profile"},
        )
        story_id = create_resp.json()["id"]

        script_resp = await api_client.get(f"/api/v1/stories/{story_id}/script")
        # Story is still pending — script not ready yet
        assert script_resp.status_code == 425  # Too Early


class TestStoriesDelete:
    @pytest.mark.asyncio
    async def test_delete_existing_story(self, api_client, mocker):
        mocker.patch("backend.api.routes.stories._run_pipeline")
        create_resp = await api_client.post(
            "/api/v1/stories/",
            json={"topic": "A valid topic for delete testing", "tone": "explanatory"},
        )
        story_id = create_resp.json()["id"]

        delete_resp = await api_client.delete(f"/api/v1/stories/{story_id}")
        assert delete_resp.status_code == 204

        get_resp = await api_client.get(f"/api/v1/stories/{story_id}")
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_story(self, api_client):
        fake_id = str(uuid.uuid4())
        response = await api_client.delete(f"/api/v1/stories/{fake_id}")
        assert response.status_code == 404


class TestStoryRewrite:
    @pytest.mark.asyncio
    async def test_rewrite_story_accepts_completed_story(self, api_client, db_session, mocker):
        mocker.patch(
            "backend.api.routes.stories._run_manual_script_rewrite",
            new=mocker.AsyncMock(return_value=None),
        )
        story = StoryORM(
            id=uuid.uuid4(),
            title="Completed story",
            topic="A valid completed story topic for rewrite testing",
            status=StoryStatus.COMPLETED,
            tone=StoryTone.EXPLANATORY,
            script_data={
                "story_id": str(uuid.uuid4()),
                "title": "Completed story",
                "logline": "A test logline.",
                "opening_hook": "A test hook.",
                "sections": [
                    {
                        "section_number": 1,
                        "title": "Act 1",
                        "narration": "A sourced narration.",
                        "estimated_seconds": 120,
                        "source_ids": [],
                    }
                ],
                "closing_statement": "A test close.",
                "total_word_count": 3,
                "estimated_duration_minutes": 0.1,
                "sources": [],
                "metadata": {},
            },
            analysis_data={"topic": "x", "executive_summary": "x", "key_findings": []},
            research_data={"topic": "x", "sources": [], "total_sources": 0},
        )
        db_session.add(story)
        await db_session.commit()

        response = await api_client.post(f"/api/v1/stories/{story.id}/rewrite")

        assert response.status_code == 202
        assert response.json()["status"] == StoryStatus.SCRIPTING

    @pytest.mark.asyncio
    async def test_rewrite_story_rejects_story_without_script(self, api_client, mocker):
        mocker.patch("backend.api.routes.stories._run_pipeline")
        create_resp = await api_client.post(
            "/api/v1/stories/",
            json={"topic": "A valid topic for rewrite rejection testing", "tone": "profile"},
        )
        story_id = create_resp.json()["id"]

        response = await api_client.post(f"/api/v1/stories/{story_id}/rewrite")

        assert response.status_code == 425


# ── Research endpoints ────────────────────────────────────────────────────────

class TestResearchEndpoints:
    @pytest.mark.asyncio
    async def test_web_search_validates_min_query_length(self, api_client):
        response = await api_client.post(
            "/api/v1/research/web-search",
            json={"query": "ab", "max_results": 5},  # < 3 chars
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_web_search_validates_max_results_bounds(self, api_client):
        response = await api_client.post(
            "/api/v1/research/web-search",
            json={"query": "valid query", "max_results": 999},  # > 20
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_news_search_validates_query(self, api_client):
        response = await api_client.post(
            "/api/v1/research/news",
            json={"query": "x"},  # < 3 chars
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_financial_overview_validates_symbol(self, api_client, mocker):
        mock_tool = mocker.AsyncMock()
        mock_tool.get_company_overview.side_effect = ValueError("Symbol not found")
        mocker.patch("backend.api.routes.research.FinancialDataTool", return_value=mock_tool)

        response = await api_client.post(
            "/api/v1/research/financial/overview",
            json={"symbol": "INVALID"},
        )
        assert response.status_code == 404


class TestBenchmarkEndpoints:
    @pytest.mark.asyncio
    async def test_benchmark_status_returns_catalog(self, api_client):
        response = await api_client.get("/api/v1/benchmarks/status")
        assert response.status_code == 200

        data = response.json()
        assert data["active_library_key"] == "combined"
        assert isinstance(data["libraries"], list)
        assert any(item["key"] == "combined" for item in data["libraries"])
        assert any(item["key"] == "bi" for item in data["libraries"])
        assert any(item["key"] == "cnbc" for item in data["libraries"])
        assert any(item["key"] == "vox" for item in data["libraries"])

    @pytest.mark.asyncio
    async def test_benchmark_references_returns_docs(self, api_client, db_session):
        db_session.add(
            BIReferenceDocORM(
                youtube_id="abc123def45",
                title="Benchmark reference doc",
                description="Reference description",
                view_count=1_200_000,
                like_count=31_000,
                duration_seconds=820,
                transcript="Transcript text",
            )
        )
        await db_session.commit()

        response = await api_client.get("/api/v1/benchmarks/references?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Benchmark reference doc"
        assert data[0]["has_transcript"] is True

    @pytest.mark.asyncio
    async def test_rebuild_benchmark_rejects_unimplemented_library(self, api_client):
        response = await api_client.post(
            "/api/v1/benchmarks/rebuild",
            json={"library_key": "unknown", "docs": 25},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_rebuild_benchmark_accepts_request(self, api_client, mocker):
        rebuild = mocker.patch(
            "backend.api.routes.benchmarks.run_benchmark_rebuild",
            new=mocker.AsyncMock(return_value=None),
        )

        response = await api_client.post(
            "/api/v1/benchmarks/rebuild",
            json={"library_key": "combined", "docs": 25},
        )

        assert response.status_code == 202
        data = response.json()
        assert data["accepted"] is True
        assert data["library_key"] == "combined"
        assert data["requested_docs"] == 50
        rebuild.assert_awaited_once_with(
            library_key="combined",
            max_docs=50,
            refresh_fraction=0.25,
        )
