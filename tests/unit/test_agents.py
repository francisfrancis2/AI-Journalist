"""
Unit tests for pipeline agents.
LLM calls are mocked with pytest-mock — no API keys needed.
"""

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
from backend.models.benchmark import BenchmarkReport
from backend.models.story import StoryTone
from backend.models.story import FinalScript, ScriptSection


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


def _make_final_script() -> FinalScript:
    return FinalScript(
        story_id=uuid.uuid4(),
        title="The AI Revolution",
        logline="How AI changed everything.",
        opening_hook="In 2024, everything changed.",
        sections=[
            ScriptSection(
                section_number=1,
                title="The Hook",
                narration="AI spending exploded, and the world scrambled to keep up.",
                estimated_seconds=120,
                source_ids=["source-1"],
            ),
            ScriptSection(
                section_number=2,
                title="The Buildout",
                narration="Cloud providers raced to build capacity while chip demand surged.",
                estimated_seconds=150,
                source_ids=["source-1"],
            ),
        ],
        closing_statement="The next phase of AI will be even more capital intensive.",
        total_word_count=320,
        estimated_duration_minutes=2.1,
        sources=[
            {
                "source_id": "source-1",
                "title": "Reuters test source",
                "url": "https://reuters.com/test",
                "credibility": "high",
                "type": "news_api",
            }
        ],
        metadata={"topic": "AI"},
    )


# ── AnalystAgent ──────────────────────────────────────────────────────────────

class TestAnalystAgent:
    @pytest.mark.asyncio
    async def test_run_returns_analysis_result(self, sample_topic):
        from backend.agents.analyst import AnalysisOutput, AnalystAgent, KeyFindingOutput

        with patch("backend.agents.analyst.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = AnalysisOutput(
                executive_summary="AI is booming.",
                key_findings=[
                    KeyFindingOutput(
                        claim="Revenue up 200%",
                        supporting_sources=["source 1"],
                        supporting_source_ids=["source 1"],
                        confidence=0.9,
                        category="financial",
                    )
                ],
                narrative_angles=["The chip race"],
                data_gaps=[],
                recommended_tone="investigative",
                controversies=[],
                notable_quotes=[],
                financial_metrics=None,
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            agent = AnalystAgent()
            package = _make_research_package(sample_topic)
            state = {
                "topic": sample_topic,
                "tone": "investigative",
                "research_package": package,
            }
            result = await agent.run(state)

        assert "analysis_result" in result
        analysis = result["analysis_result"]
        assert isinstance(analysis, AnalysisResult)
        assert analysis.executive_summary == "AI is booming."
        assert len(analysis.key_findings) == 1
        assert analysis.key_findings[0].supporting_source_ids == [
            package.top_sources(12)[0].source_id
        ]

    @pytest.mark.asyncio
    async def test_run_raises_on_invalid_json(self, sample_topic):
        from backend.agents.analyst import AnalystAgent

        with patch("backend.agents.analyst.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.side_effect = ValueError("did not return valid JSON")

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            agent = AnalystAgent()
            state = {
                "topic": sample_topic,
                "tone": "explanatory",
                "research_package": _make_research_package(),
            }
            with pytest.raises(ValueError, match="Analyst failed after 3 attempts: did not return valid JSON"):
                await agent.run(state)


# ── EvaluatorAgent ────────────────────────────────────────────────────────────

class TestEvaluatorAgent:
    @pytest.mark.asyncio
    async def test_run_approves_high_scoring_storyline(self, sample_topic):
        from backend.agents.evaluator import CriteriaOutput, EvaluatorAgent, EvaluatorOutput

        with patch("backend.agents.evaluator.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = EvaluatorOutput(
                criteria=CriteriaOutput(
                    factual_accuracy=0.9,
                    narrative_coherence=0.9,
                    audience_engagement=0.9,
                    source_diversity=0.9,
                    originality=0.9,
                    production_feasibility=0.9,
                ),
                strengths=["Well sourced"],
                weaknesses=[],
                improvement_suggestions=[],
                requires_additional_research=False,
                evaluator_notes="Ready to produce.",
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

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
        from backend.agents.evaluator import CriteriaOutput, EvaluatorAgent, EvaluatorOutput

        with patch("backend.agents.evaluator.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = EvaluatorOutput(
                criteria=CriteriaOutput(
                    factual_accuracy=0.4,
                    narrative_coherence=0.4,
                    audience_engagement=0.4,
                    source_diversity=0.4,
                    originality=0.4,
                    production_feasibility=0.4,
                ),
                strengths=[],
                weaknesses=["Weak sourcing"],
                improvement_suggestions=["Add more data"],
                requires_additional_research=True,
                evaluator_notes="Needs work.",
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

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
        from backend.agents.storyline_creator import (
            StoryActOutput,
            StorylineCreatorAgent,
            StorylineCreatorOutput,
            StorylineProposalOutput,
        )

        mock_response = StorylineCreatorOutput(
            proposals=[
                StorylineProposalOutput(
                    title="The Chip Wars",
                    logline="How semiconductors changed the world.",
                    opening_hook="In 2024...",
                    unique_angle="Supply chain angle",
                    target_audience="Business viewers",
                    tone="investigative",
                    acts=[
                        StoryActOutput(
                            act_number=1,
                            act_title="The Hook",
                            purpose="Grab attention",
                            key_points=["Point A", "Point B"],
                            estimated_duration_seconds=120,
                            required_visuals=["Factory footage"],
                        )
                    ],
                    closing_statement="The future of chips.",
                )
            ],
            recommended_proposal_index=0,
        )

        with patch("backend.agents.storyline_creator.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = mock_response

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

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

    @pytest.mark.asyncio
    async def test_run_uses_deterministic_fallback_after_empty_structured_responses(self, sample_topic):
        from backend.agents.storyline_creator import StorylineCreatorAgent

        with patch("backend.agents.storyline_creator.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.side_effect = [
                ValueError("1 validation error for StorylineCreatorOutput proposals Field required"),
                ValueError("1 validation error for StorylineCreatorOutput proposals Field required"),
                ValueError("1 validation error for StorylineCreatorOutput proposals Field required"),
            ]

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            mock_base.ainvoke.side_effect = [
                MagicMock(content='{}'),
                MagicMock(content='{}'),
                MagicMock(content='{}'),
            ]
            MockLLM.return_value = mock_base

            agent = StorylineCreatorAgent()
            state = {
                "topic": sample_topic,
                "tone": "investigative",
                "refinement_cycle": 0,
                "analysis_result": _make_analysis_result(sample_topic),
            }
            result = await agent.run(state)

        assert "storyline_proposals" in result
        assert len(result["storyline_proposals"]) >= 1
        assert result["selected_storyline"].title


# ── ScriptwriterAgent ────────────────────────────────────────────────────────

class TestScriptwriterAgent:
    @pytest.mark.asyncio
    async def test_run_preserves_targeting_and_section_source_ids(self, sample_topic):
        from backend.agents.scriptwriter import ActOutput, ScriptwriterAgent

        package = _make_research_package(sample_topic)
        source_id = package.top_sources(20)[0].source_id
        analysis = _make_analysis_result(sample_topic)
        analysis.key_findings[0].supporting_source_ids = [source_id]

        with patch("backend.agents.scriptwriter.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = ActOutput(
                narration="AI spending is rising because demand is concentrated in a few suppliers.",
                word_count=12,
                source_ids=[source_id, "unknown-source"],
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            with patch(
                "backend.agents.scriptwriter.upload_script_to_s3",
                new=AsyncMock(return_value="scripts/test.md"),
            ):
                result = await ScriptwriterAgent().run({
                    "story_id": str(uuid.uuid4()),
                    "topic": sample_topic,
                    "selected_storyline": _make_storyline(),
                    "analysis_result": analysis,
                    "research_package": package,
                    "evaluation_report": None,
                    "target_duration_minutes": 15,
                    "target_audience": "Business viewers",
                })

        script = result["final_script"]
        assert result["script_s3_key"] == "scripts/test.md"
        assert script.metadata["target_duration_minutes"] == 15
        assert script.metadata["target_audience"] == "Business viewers"
        assert all(section.source_ids == [source_id] for section in script.sections)
        assert script.sources[0]["source_id"] == source_id


# ── ScriptEvaluatorAgent ─────────────────────────────────────────────────────

class TestScriptEvaluatorAgent:
    @pytest.mark.asyncio
    async def test_run_returns_script_audit_report(self, sample_topic):
        from backend.agents.script_evaluator import ScriptAuditOutput, ScriptEvaluatorAgent
        from backend.models.story import (
            BenchmarkComparison,
            ScriptAuditCriteria,
            ScriptSectionAudit,
        )

        with patch("backend.agents.script_evaluator.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = ScriptAuditOutput(
                criteria=ScriptAuditCriteria(
                    hook_strength=0.9,
                    narrative_flow=0.85,
                    evidence_and_specificity=0.8,
                    pacing=0.86,
                    writing_quality=0.88,
                    production_readiness=0.9,
                ),
                audit_summary="Strong script with a slightly thin middle section.",
                strengths=["Sharp opening narration"],
                weaknesses=["Act 2 needs more concrete evidence"],
                rewrite_priorities=["Add one specific data point to Act 2"],
                section_audits=[
                    ScriptSectionAudit(
                        section_number=1,
                        title="The Hook",
                        score=0.92,
                        summary="Opens with clear stakes.",
                        strengths=["Immediate tension"],
                        weaknesses=[],
                        benchmark_notes=["Opens in a BI-style high-stakes frame."],
                        rewrite_recommendation="Keep this opening mostly intact.",
                    ),
                    ScriptSectionAudit(
                        section_number=2,
                        title="The Buildout",
                        score=0.74,
                        summary="Useful context, but not enough specifics.",
                        strengths=["Clear bridge from the opening"],
                        weaknesses=["Needs more numbers"],
                        benchmark_notes=["Could use BI-style numeric specificity."],
                        rewrite_recommendation="Add a stat and a concrete corporate example.",
                    ),
                ],
                benchmark_comparison=BenchmarkComparison(
                    closest_reference_title="How AI Data Centers Changed The Economy",
                    alignment_summary="Close to BI in hook and structure, lighter on data density.",
                    hook_comparison="The hook is strong and immediate.",
                    structure_comparison="The structure follows a clear problem-to-explanation arc.",
                    data_density_comparison="The script needs more numbers in the middle.",
                    closing_comparison="The close is forward-looking but could land harder.",
                    best_in_class_takeaways=["Use one headline number in each major section."],
                ),
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            agent = ScriptEvaluatorAgent()
            state = {
                "topic": sample_topic,
                "final_script": _make_final_script(),
                "evaluation_report": EvaluationReport(
                    criteria=EvaluationCriteria(
                        factual_accuracy=0.8,
                        narrative_coherence=0.8,
                        audience_engagement=0.8,
                        source_diversity=0.8,
                        originality=0.8,
                        production_feasibility=0.8,
                    ),
                    strengths=["Good structure"],
                    weaknesses=["Could use more sourcing"],
                    improvement_suggestions=["Add more specifics"],
                    evaluator_notes="Promising storyline.",
                ),
                "benchmark_report": BenchmarkReport(
                    bi_similarity_score=0.76,
                    hook_potency=0.8,
                    title_formula_fit=0.75,
                    act_architecture=0.8,
                    data_density=0.7,
                    human_narrative_placement=0.72,
                    tension_release_rhythm=0.78,
                    closing_device=0.74,
                    closest_reference_title="How AI Data Centers Changed The Economy",
                    gaps=["Needs more numbers"],
                    strengths=["Good pacing"],
                    grade="B",
                ),
            }

            with patch.object(agent, "_load_library", return_value=None):
                result = await agent.run(state)

        assert "script_audit_report" in result
        report = result["script_audit_report"]
        assert report.grade == "A"
        assert report.ready_for_production is True
        assert len(report.section_audits) == 2
        assert report.benchmark_comparison is None
