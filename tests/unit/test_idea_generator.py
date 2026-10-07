"""Focused tests for Idea Generator V2 contracts and deterministic validation."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from pydantic import ValidationError

from backend.agents.idea_generator import (
    IdeaGeneratorAgent,
    IdeaCandidate,
    PreparedSignal,
    PreparedSource,
    _score_candidate,
)
from backend.config import settings
from backend.models.idea_generation import IdeaFormat
from backend.models.research import ResearchPackage


def _source(reference_id: str, domain: str, *, uae: bool) -> PreparedSource:
    return PreparedSource(
        id=uuid.uuid4(),
        reference_id=reference_id,
        title=f"Current report from {domain}",
        url=f"https://{domain}/report",
        domain=domain,
        published_at=datetime.now(timezone.utc),
        excerpt="A current, named business development in the United Arab Emirates with supporting data.",
        source_type="news_api",
        credibility="high",
        is_uae_relevant=uae,
        is_primary=False,
        content_hash=reference_id * 32,
    )


def _candidate(**updates) -> IdeaCandidate:
    payload = {
        "sector": "Logistics",
        "title": "Inside the UAE's next logistics operating model",
        "premise": "Follow the companies and workers changing how high-value goods move through the UAE.",
        "why_now": "New infrastructure and company investment make the operating shift visible now.",
        "uae_relevance": "The change is unfolding across named UAE logistics hubs and businesses.",
        "central_tension": "Faster automated movement depends on access, economics, and human adoption.",
        "target_audience": "Business viewers interested in technology and operations",
        "business_significance": "The shift could change costs, delivery times, and regional competitive advantage.",
        "format_details": {
            "protagonist_or_system": "A logistics operator",
            "access_path": "Warehouses and dispatch teams",
            "visual_world": "Ports, depots, and control rooms",
            "story_arc": "Promise, operational test, and consequence",
        },
        "source_ids": ["s1", "s2"],
        "signal_keys": ["v1"],
        "verification_gaps": [],
    }
    payload.update(updates)
    return IdeaCandidate.model_validate(payload)


def test_candidate_schema_rejects_recommended_next_steps() -> None:
    payload = _candidate().model_dump()
    payload["recommended_next_steps"] = ["Call an expert"]
    with pytest.raises(ValidationError):
        IdeaCandidate.model_validate(payload)


def test_scoring_requires_two_independent_domains_and_current_uae_evidence() -> None:
    first = _source("s1", "wam.ae", uae=True)
    second = _source("s2", "reuters.com", uae=False)
    signal = PreparedSignal(
        id=uuid.uuid4(),
        key="v1",
        provider="vidiq",
        signal_type="keyword_demand",
        topic="UAE logistics",
        geography="AE",
        geography_meaning="United Arab Emirates search volume",
        metric="country_volume",
        values={"countryVolume": 1200},
    )
    scored, reason = _score_candidate(
        _candidate(),
        {"s1": first, "s2": second},
        {"v1": signal},
    )
    assert reason is None
    assert scored is not None
    assert scored.score <= 100
    assert scored.source_ids == [first.id, second.id]
    assert scored.signal_ids == [signal.id]


def test_scoring_rejects_single_domain_even_with_two_source_ids() -> None:
    first = _source("s1", "example.ae", uae=True)
    second = _source("s2", "example.ae", uae=True)
    scored, reason = _score_candidate(_candidate(), {"s1": first, "s2": second}, {})
    assert scored is None
    assert reason == "fewer_than_two_independent_domains"


def test_scoring_rejects_explicit_uae_institutional_attack_framing() -> None:
    first = _source("s1", "wam.ae", uae=True)
    second = _source("s2", "reuters.com", uae=False)
    candidate = _candidate(
        premise="An investigation arguing that UAE government corruption is driving a logistics cover-up.",
    )
    scored, reason = _score_candidate(candidate, {"s1": first, "s2": second}, {})
    assert scored is None
    assert reason == "editorial_policy_conflict"


@pytest.mark.asyncio
async def test_vidiq_idea_trends_fail_open_when_disabled(monkeypatch) -> None:
    from backend.tools.vidiq import VidIQTool

    tool = VidIQTool()
    tool._api_key = None
    assert await tool.fetch_idea_trends() is None


@pytest.mark.asyncio
async def test_idea_generator_passes_three_search_deep_research_budget(mocker) -> None:
    agent = IdeaGeneratorAgent.__new__(IdeaGeneratorAgent)
    gather = AsyncMock(return_value=ResearchPackage(topic="UAE business"))
    agent._research = SimpleNamespace(gather_package=gather)
    mocker.patch(
        "backend.agents.idea_generator.VidIQTool.fetch_idea_trends",
        new=AsyncMock(return_value=None),
    )

    with pytest.raises(RuntimeError, match="insufficient_evidence"):
        await agent.generate(IdeaFormat.DOCUMENTARY)

    assert gather.await_args.kwargs["deep_max_uses"] == 3
    assert gather.await_args.kwargs["deep_max_uses"] == settings.anthropic_deep_research_idea_max_uses
