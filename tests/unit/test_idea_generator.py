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


def test_scoring_keeps_a_single_domain_candidate_but_ranks_it_lower() -> None:
    """Thin sourcing is a scoring penalty, not a rejection.

    Enforcing it meant validation decided how many ideas a run produced. The
    criterion now lives in the prompt and in the ranking.
    """
    # Hold UAE relevance and recency equal so only domain independence differs.
    weak, reason = _score_candidate(
        _candidate(),
        {"s1": _source("s1", "example.ae", uae=True), "s2": _source("s2", "example.ae", uae=True)},
        {},
    )
    assert reason is None
    assert weak is not None

    strong, _ = _score_candidate(
        _candidate(),
        {"s1": _source("s1", "example.ae", uae=True), "s2": _source("s2", "gulfnews.com", uae=True)},
        {},
    )
    assert strong is not None
    assert strong.score > weak.score, "two independent domains must outrank one"


def test_scoring_keeps_a_candidate_with_no_current_uae_source_but_ranks_it_lower() -> None:
    # Both non-UAE, so no source can be "current UAE"; domains stay independent.
    stale_first = _source("s1", "reuters.com", uae=False)
    stale_second = _source("s2", "ft.com", uae=False)
    stale, reason = _score_candidate(_candidate(), {"s1": stale_first, "s2": stale_second}, {})
    assert reason is None
    assert stale is not None

    current_first = _source("s1", "wam.ae", uae=True)
    current_second = _source("s2", "reuters.com", uae=False)
    current, _ = _score_candidate(_candidate(), {"s1": current_first, "s2": current_second}, {})
    assert current is not None
    assert current.score > stale.score, "a current UAE source must outrank none"


def test_scoring_rejects_a_candidate_whose_sources_do_not_exist() -> None:
    """Citing an ID that resolves to nothing is a hallucination, not a weak idea."""
    scored, reason = _score_candidate(_candidate(), {}, {})
    assert scored is None
    assert reason == "no_resolvable_sources"


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
async def test_idea_generator_uses_shared_initial_research_with_two_search_budget(mocker) -> None:
    agent = IdeaGeneratorAgent.__new__(IdeaGeneratorAgent)
    gather = AsyncMock(return_value=ResearchPackage(topic="UAE business"))
    agent._research = SimpleNamespace(gather_initial_package=gather)
    mocker.patch(
        "backend.agents.idea_generator.VidIQTool.fetch_idea_trends",
        new=AsyncMock(return_value=None),
    )

    with pytest.raises(RuntimeError, match="insufficient_evidence"):
        await agent.generate(IdeaFormat.DOCUMENTARY)

    assert gather.await_args.kwargs["deep_max_uses"] == 2
    assert gather.await_args.kwargs["deep_max_uses"] == settings.anthropic_deep_research_idea_max_uses


def test_idea_generator_synthesis_uses_sonnet(mocker) -> None:
    constructor = mocker.patch("backend.agents.idea_generator.ChatAnthropic")
    mocker.patch("backend.agents.idea_generator.ResearchAgent")

    IdeaGeneratorAgent()

    assert constructor.call_count == 2
    assert all(
        call.kwargs["model"] == settings.claude_model
        for call in constructor.call_args_list
    )


class TestRunCeilings:
    """The 5-minute deadline and the $1 spend cap."""

    def test_deadline_clamps_a_phase_to_the_time_left(self) -> None:
        from backend.agents.idea_generator import _Deadline

        deadline = _Deadline(10)
        # A phase budget larger than the ceiling is cut down to it, so the sum
        # of the phase budgets can never outlast the run as a whole.
        assert deadline.allot(300) == pytest.approx(10, abs=0.5)
        # A phase that fits is handed its full budget.
        assert deadline.allot(3) == pytest.approx(3)

    def test_expired_deadline_allots_nothing(self) -> None:
        from backend.agents.idea_generator import _Deadline

        assert _Deadline(0).allot(300) == 0

    def test_phase_budgets_fit_inside_the_ceiling(self) -> None:
        """The nominal budgets plus the persist reserve must not exceed 5 minutes."""
        assert settings.idea_generator_total_timeout_seconds <= 300
        assert (
            settings.idea_generator_research_timeout_seconds
            + settings.idea_generator_persist_reserve_seconds
            < settings.idea_generator_total_timeout_seconds
        )

    @pytest.mark.asyncio
    async def test_generate_opens_a_spend_ledger_for_the_whole_run(self, mocker) -> None:
        """Research tools must be able to charge the run without being passed the ledger."""
        from backend.services.cost_ledger import current_ledger

        seen: dict[str, object] = {}

        async def gather(**kwargs):
            seen["ledger"] = current_ledger()
            return ResearchPackage(topic="UAE business")

        agent = IdeaGeneratorAgent.__new__(IdeaGeneratorAgent)
        agent._research = SimpleNamespace(gather_initial_package=gather)
        mocker.patch(
            "backend.agents.idea_generator.VidIQTool.fetch_idea_trends",
            new=AsyncMock(return_value=None),
        )

        with pytest.raises(RuntimeError, match="insufficient_evidence"):
            await agent.generate(IdeaFormat.DOCUMENTARY)

        ledger = seen["ledger"]
        assert ledger is not None, "research ran outside the run's ledger"
        assert ledger.budget_usd == settings.idea_generator_max_cost_usd
        # And the context is clean afterwards, so one run cannot charge another.
        assert current_ledger() is None


class TestCandidateFieldBudgets:
    """A production run failed because two fields ran slightly over their cap.

    Structured output validates the whole CandidateSet at once, so two long
    paragraphs lost all four candidates and the run reported only a generic
    "could not complete". The caps are a guard against runaway output, not a
    style rule, and the DB columns are Text with no limit.
    """

    def test_a_long_but_reasonable_business_significance_is_accepted(self) -> None:
        # ~1,100 characters: longer than the old 900 cap, well within a
        # paragraph a producer would actually write.
        long_text = (
            "The UAE logistics market is forecast to grow substantially as "
            "regional rerouting shifts volumes toward Jebel Ali. "
        ) * 9
        assert 900 < len(long_text) <= 1600
        candidate = _candidate(business_significance=long_text)
        assert candidate.business_significance == long_text

    def test_runaway_output_is_bounded_not_rejected(self) -> None:
        """The cap still bounds what gets stored; it no longer fails the run.

        This replaces an earlier expectation that an overrun raises. Rejecting
        was the behaviour that lost four candidates to two long paragraphs in
        production, so the guard now bounds the value instead.
        """
        candidate = _candidate(business_significance="x" * 50_000)
        assert len(candidate.business_significance) <= 1600

    def test_every_prose_field_accepts_a_full_paragraph(self) -> None:
        """The 900-character trip-wire sat on three sibling fields, not one."""
        paragraph = "Jebel Ali handled record container volumes this quarter. " * 18
        assert len(paragraph) > 900
        candidate = _candidate(
            premise=paragraph,
            why_now=paragraph[:1100],
            uae_relevance=paragraph[:1100],
            central_tension=paragraph[:950],
            business_significance=paragraph,
        )
        assert candidate.premise == paragraph


    def test_overrun_is_trimmed_rather_than_failing_the_set(self) -> None:
        """The production failure mode, made impossible.

        Raising the caps only made an overrun less likely. Because structured
        output validates the whole CandidateSet at once, any overrun still lost
        every candidate -- so the field is trimmed instead of rejected.
        """
        candidate = _candidate(business_significance="word " * 1000)  # ~5000 chars
        assert len(candidate.business_significance) <= 1600
        assert not candidate.business_significance.endswith(" ")
        # Trimmed at a word boundary, not mid-word.
        assert candidate.business_significance.split()[-1] == "word"

    def test_trimming_applies_to_every_prose_field(self) -> None:
        candidate = _candidate(
            premise="alpha " * 1000,
            why_now="beta " * 1000,
            uae_relevance="gamma " * 1000,
            central_tension="delta " * 1000,
            business_significance="epsilon " * 1000,
        )
        for field, limit in (
            ("premise", 1600), ("why_now", 1200), ("uae_relevance", 1200),
            ("central_tension", 1000), ("business_significance", 1600),
        ):
            assert len(getattr(candidate, field)) <= limit, field

    def test_a_whole_set_survives_one_verbose_candidate(self) -> None:
        """What actually broke in production: one long field, four ideas lost."""
        from backend.agents.idea_generator import CandidateSet

        candidates = [
            _candidate(title="Idea one that is long enough"),
            _candidate(title="Idea two that is long enough", business_significance="word " * 1000),
            _candidate(title="Idea three that is long enough"),
        ]
        result = CandidateSet(candidates=candidates)
        assert len(result.candidates) == 3, "a verbose candidate must not lose the others"
