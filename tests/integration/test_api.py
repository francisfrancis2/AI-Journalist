"""
Integration tests for the FastAPI REST API.
Uses an in-memory SQLite database via the db_session fixture from conftest.
The LangGraph pipeline is NOT invoked in these tests — we test the API layer only.
"""

import uuid

import pytest

from backend.models.story import StoryStatus, StoryTone


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
