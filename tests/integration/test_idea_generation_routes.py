"""API lifecycle tests for the persisted Idea Generator workspace."""

from unittest.mock import AsyncMock

import pytest


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

