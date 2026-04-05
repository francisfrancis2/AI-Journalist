"""
Unit tests for pipeline agents.
LLM calls are mocked with pytest-mock — no API keys needed.
"""

import json
import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.models.research import (
    AnalysisResult,
    EvaluationCriteria,
    EvaluationReport,
    KeyFinding,
    RawSource,
    ResearchPackage,
    SourceCredibility,
    SourceType,
    StoryAct,
    StorylineProposal,
)
from backend.models.story import StoryTone


def _make_raw_source(score: float = 0.7) -> RawSource:
    return RawSource(
        source_type=SourceType.WEB_SEARCH,
        url="https://reuters.com/test",
        title="Test Article",
        content="Some important test content about the topic.",
        credibility=SourceCredibility.HIGH,
        relevance_score=score,
    )


def _make_research_package(topic: str = "AI") -> ResearchPackage:
    pkg = ResearchPackage(topic=topic)
    for i in range(5):
        pkg.add_source(_make_raw_source(float(i + 1) / 10))
    return pkg


def _make_analysis_result(topic: str = "AI") -> AnalysisResult:
    return AnalysisResult(
        topic=topic,
        executive_summary="AI is transforming industries.",
        key_findings=[
            KeyFinding(claim="AI revenues grew 200%", confidence=0.9, category="financial")
        ],
        narrative_angles=["The human cost of automation"],
        recommended_tone="investigative",
    )


def _make_storyline() -> StorylineProposal:
    acts = [
        StoryAct(
            act_number=i,
            act_title=f"Act {i}",
            purpose="purpose",
            key_points=["point1", "point2"],
            estimated_duration_seconds=120,
        )
        for i in range(1, 6)
    ]
    proposal = StorylineProposal(
        title="The AI Revolution",
        logline="How AI changed everything.",
        opening_hook="In 2024, everything changed.",
        acts=acts,
        closing_statement="The future is uncertain.",
        unique_angle="Human angle",
        target_audience="Business professionals",
        tone="investigative",
    )
    proposal.compute_duration()
    return proposal


# ── AnalystAgent ──────────────────────────────────────────────────────────────

class TestAnalystAgent:
    @pytest.mark.asyncio
    async def test_run_returns_analysis_result(self, sample_topic):
        from backend.agents.analyst import AnalystAgent

        mock_llm_response = json.dumps({
            "executive_summary": "AI is booming.",
            "key_findings": [
                {"claim": "Revenue up 200%", "supporting_sources": [], "confidence": 0.9, "category": "financial"}
            ],
            "narrative_angles": ["The chip race"],
            "data_gaps": [],
            "recommended_tone": "investigative",
            "controversies": [],
            "notable_quotes": [],
            "financial_metrics": None,
        })

        with patch("backend.agents.analyst.ChatAnthropic") as MockLLM:
            mock_instance = AsyncMock()
            mock_instance.ainvoke.return_value = MagicMock(content=mock_llm_response)
            MockLLM.return_value = mock_instance

            agent = AnalystAgent()
            state = {
                "topic": sample_topic,
                "tone": "investigative",
                "research_package": _make_research_package(sample_topic),
            }
            result = await agent.run(state)

        assert "analysis_result" in result
        analysis = result["analysis_result"]
        assert isinstance(analysis, AnalysisResult)
        assert analysis.executive_summary == "AI is booming."
        assert len(analysis.key_findings) == 1

    @pytest.mark.asyncio
    async def test_run_raises_on_invalid_json(self, sample_topic):
        from backend.agents.analyst import AnalystAgent

        with patch("backend.agents.analyst.ChatAnthropic") as MockLLM:
            mock_instance = AsyncMock()
            mock_instance.ainvoke.return_value = MagicMock(content="not json at all")
            MockLLM.return_value = mock_instance

            agent = AnalystAgent()
            state = {
                "topic": sample_topic,
                "tone": "explanatory",
                "research_package": _make_research_package(),
            }
            with pytest.raises(ValueError, match="did not return valid JSON"):
                await agent.run(state)


# ── EvaluatorAgent ────────────────────────────────────────────────────────────

class TestEvaluatorAgent:
    @pytest.mark.asyncio
    async def test_run_approves_high_scoring_storyline(self, sample_topic):
        from backend.agents.evaluator import EvaluatorAgent

        mock_response = json.dumps({
            "criteria": {
                "factual_accuracy": 0.9,
                "narrative_coherence": 0.9,
                "audience_engagement": 0.9,
                "source_diversity": 0.9,
                "originality": 0.9,
                "production_feasibility": 0.9,
            },
            "strengths": ["Well sourced"],
            "weaknesses": [],
            "improvement_suggestions": [],
            "requires_additional_research": False,
            "evaluator_notes": "Ready to produce.",
        })

        with patch("backend.agents.evaluator.ChatAnthropic") as MockLLM:
            mock_instance = AsyncMock()
            mock_instance.ainvoke.return_value = MagicMock(content=mock_response)
            MockLLM.return_value = mock_instance

            agent = EvaluatorAgent()
            state = {
                "topic": sample_topic,
                "selected_storyline": _make_storyline(),
                "analysis_result": _make_analysis_result(sample_topic),
                "research_package": _make_research_package(sample_topic),
            }
            result = await agent.run(state)

        assert result["approved_for_scripting"] is True
        assert result["needs_more_research"] is False
        assert result["evaluation_report"].overall_score >= 0.75

    @pytest.mark.asyncio
    async def test_run_rejects_low_scoring_storyline(self, sample_topic):
        from backend.agents.evaluator import EvaluatorAgent

        mock_response = json.dumps({
            "criteria": {
                "factual_accuracy": 0.4,
                "narrative_coherence": 0.4,
                "audience_engagement": 0.4,
                "source_diversity": 0.4,
                "originality": 0.4,
                "production_feasibility": 0.4,
            },
            "strengths": [],
            "weaknesses": ["Weak sourcing"],
            "improvement_suggestions": ["Add more data"],
            "requires_additional_research": True,
            "evaluator_notes": "Needs work.",
        })

        with patch("backend.agents.evaluator.ChatAnthropic") as MockLLM:
            mock_instance = AsyncMock()
            mock_instance.ainvoke.return_value = MagicMock(content=mock_response)
            MockLLM.return_value = mock_instance

            agent = EvaluatorAgent()
            state = {
                "topic": sample_topic,
                "selected_storyline": _make_storyline(),
                "analysis_result": _make_analysis_result(sample_topic),
                "research_package": _make_research_package(sample_topic),
            }
            result = await agent.run(state)

        assert result["approved_for_scripting"] is False
        assert result["needs_more_research"] is True


# ── StorylineCreatorAgent ─────────────────────────────────────────────────────

class TestStorylineCreatorAgent:
    @pytest.mark.asyncio
    async def test_run_returns_proposals(self, sample_topic):
        from backend.agents.storyline_creator import StorylineCreatorAgent

        mock_response = json.dumps({
            "proposals": [
                {
                    "title": "The Chip Wars",
                    "logline": "How semiconductors changed the world.",
                    "opening_hook": "In 2024...",
                    "unique_angle": "Supply chain angle",
                    "target_audience": "Business viewers",
                    "tone": "investigative",
                    "acts": [
                        {
                            "act_number": 1,
                            "act_title": "The Hook",
                            "purpose": "Grab attention",
                            "key_points": ["Point A", "Point B"],
                            "estimated_duration_seconds": 120,
                            "required_visuals": ["Factory footage"],
                        }
                    ],
                    "closing_statement": "The future of chips.",
                }
            ],
            "recommended_proposal_index": 0,
        })

        with patch("backend.agents.storyline_creator.ChatAnthropic") as MockLLM:
            mock_instance = AsyncMock()
            mock_instance.ainvoke.return_value = MagicMock(content=mock_response)
            MockLLM.return_value = mock_instance

            agent = StorylineCreatorAgent()
            state = {
                "topic": sample_topic,
                "tone": "investigative",
                "refinement_cycle": 0,
                "analysis_result": _make_analysis_result(sample_topic),
            }
            result = await agent.run(state)

        assert "storyline_proposals" in result
        assert "selected_storyline" in result
        assert len(result["storyline_proposals"]) == 1
        assert result["selected_storyline"].title == "The Chip Wars"
