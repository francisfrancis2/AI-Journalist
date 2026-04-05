"""
Unit tests for Pydantic research and story models.
No external dependencies — pure model validation.
"""

import uuid
from datetime import datetime, timezone

import pytest

from backend.models.research import (
    AnalysisResult,
    EvaluationCriteria,
    EvaluationReport,
    KeyFinding,
    RawSource,
    ResearchPackage,
    ResearchQuery,
    SourceCredibility,
    SourceType,
    StoryAct,
    StorylineProposal,
)
from backend.models.story import (
    FinalScript,
    ScriptSection,
    StoryCreate,
    StoryStatus,
    StoryTone,
)


# ── RawSource ─────────────────────────────────────────────────────────────────

class TestRawSource:
    def test_minimal_creation(self):
        src = RawSource(
            source_type=SourceType.WEB_SEARCH,
            title="Test Article",
            content="Some content here.",
        )
        assert src.source_type == SourceType.WEB_SEARCH
        assert src.credibility == SourceCredibility.MEDIUM
        assert src.relevance_score == 0.5

    def test_relevance_score_bounds(self):
        with pytest.raises(Exception):
            RawSource(
                source_type=SourceType.NEWS_API,
                title="t",
                content="c",
                relevance_score=1.5,  # > 1.0, should fail
            )

    def test_full_creation(self):
        src = RawSource(
            source_type=SourceType.FINANCIAL_DATA,
            url="https://finance.yahoo.com/quote/NVDA",
            title="NVIDIA Corp",
            content="Market cap: $3T",
            author="Finance Bot",
            published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            credibility=SourceCredibility.HIGH,
            relevance_score=0.95,
            metadata={"ticker": "NVDA"},
        )
        assert src.credibility == SourceCredibility.HIGH
        assert src.metadata["ticker"] == "NVDA"


# ── ResearchPackage ───────────────────────────────────────────────────────────

class TestResearchPackage:
    def _make_source(self, score: float = 0.5) -> RawSource:
        return RawSource(
            source_type=SourceType.WEB_SEARCH,
            title="Test",
            content="Content",
            relevance_score=score,
        )

    def test_add_source_updates_count(self):
        pkg = ResearchPackage(topic="AI")
        assert pkg.total_sources == 0
        pkg.add_source(self._make_source())
        assert pkg.total_sources == 1

    def test_top_sources_sorted_by_relevance(self):
        pkg = ResearchPackage(topic="AI")
        pkg.add_source(self._make_source(0.3))
        pkg.add_source(self._make_source(0.9))
        pkg.add_source(self._make_source(0.6))
        top = pkg.top_sources(2)
        assert len(top) == 2
        assert top[0].relevance_score == 0.9
        assert top[1].relevance_score == 0.6

    def test_top_sources_cap_at_n(self):
        pkg = ResearchPackage(topic="AI")
        for i in range(10):
            pkg.add_source(self._make_source(float(i) / 10))
        assert len(pkg.top_sources(3)) == 3


# ── EvaluationCriteria ────────────────────────────────────────────────────────

class TestEvaluationCriteria:
    def test_overall_score_weighted(self):
        criteria = EvaluationCriteria(
            factual_accuracy=1.0,
            narrative_coherence=1.0,
            audience_engagement=1.0,
            source_diversity=1.0,
            originality=1.0,
            production_feasibility=1.0,
        )
        assert criteria.overall_score == pytest.approx(1.0)

    def test_overall_score_partial(self):
        criteria = EvaluationCriteria(
            factual_accuracy=0.8,
            narrative_coherence=0.8,
            audience_engagement=0.8,
            source_diversity=0.8,
            originality=0.8,
            production_feasibility=0.8,
        )
        assert criteria.overall_score == pytest.approx(0.8)

    def test_overall_score_zeros(self):
        criteria = EvaluationCriteria()
        assert criteria.overall_score == pytest.approx(0.0)


# ── EvaluationReport ──────────────────────────────────────────────────────────

class TestEvaluationReport:
    def test_compute_overall_approves_above_threshold(self):
        criteria = EvaluationCriteria(
            factual_accuracy=0.9,
            narrative_coherence=0.9,
            audience_engagement=0.9,
            source_diversity=0.9,
            originality=0.9,
            production_feasibility=0.9,
        )
        report = EvaluationReport(criteria=criteria)
        report.compute_overall()
        assert report.approved_for_scripting is True
        assert report.overall_score >= 0.75

    def test_compute_overall_rejects_below_threshold(self):
        criteria = EvaluationCriteria(
            factual_accuracy=0.5,
            narrative_coherence=0.5,
            audience_engagement=0.5,
            source_diversity=0.5,
            originality=0.5,
            production_feasibility=0.5,
        )
        report = EvaluationReport(criteria=criteria)
        report.compute_overall()
        assert report.approved_for_scripting is False


# ── StorylineProposal ─────────────────────────────────────────────────────────

class TestStorylineProposal:
    def test_compute_duration(self):
        acts = [
            StoryAct(
                act_number=i,
                act_title=f"Act {i}",
                purpose="test",
                key_points=["point"],
                estimated_duration_seconds=120,
            )
            for i in range(1, 6)
        ]
        proposal = StorylineProposal(
            title="Test Film",
            logline="A story.",
            opening_hook="Hook.",
            acts=acts,
            closing_statement="The end.",
            unique_angle="Fresh",
            target_audience="Adults",
            tone="explanatory",
        )
        proposal.compute_duration()
        assert proposal.total_estimated_duration_seconds == 600  # 5 * 120


# ── StoryCreate ───────────────────────────────────────────────────────────────

class TestStoryCreate:
    def test_valid_creation(self):
        story = StoryCreate(topic="This is a valid topic of sufficient length.")
        assert story.tone == StoryTone.EXPLANATORY

    def test_topic_too_short(self):
        with pytest.raises(Exception):
            StoryCreate(topic="Short")  # < 10 chars

    def test_topic_blank_stripped(self):
        with pytest.raises(Exception):
            StoryCreate(topic="   ")

    def test_tone_options(self):
        for tone in StoryTone:
            story = StoryCreate(topic="This is a valid topic long enough.", tone=tone)
            assert story.tone == tone
