"""
Unit tests for pipeline agents.
LLM calls are mocked with pytest-mock — no API keys needed.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.models.research import (
    AnalysisResult,
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
from backend.services.benchmarking import BenchmarkLibraryStatus
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


# ── Research routing helpers ──────────────────────────────────────────────────

class TestResearchRouting:
    def test_researcher_normalise_sources_keeps_rss_with_newsapi(self):
        from backend.agents.research import ResearchPlan, ResearchAgent

        plan = ResearchPlan(
            topic_type="news",
            use_sources=["newsapi"],
            primary_queries=[],
            deep_dive_queries=[],
            human_story_queries=[],
            financial_symbols=[],
            rss_keyword="ai",
        )

        selected = ResearchAgent._normalise_sources(plan)

        assert "tavily" in selected
        assert "newsapi" in selected
        assert "rss" in selected

    def test_researcher_balanced_query_cap_preserves_evidence_lanes(self):
        from backend.agents.research import ResearchPlan, ResearchAgent

        plan = ResearchPlan(
            topic_type="mixed",
            use_sources=["tavily"],
            economics_queries=["cost 1", "cost 2", "cost 3"],
            operations_queries=["operations 1", "operations 2"],
            human_story_queries=["human 1", "human 2"],
            origin_queries=["origin 1"],
            counterintuitive_queries=["surprise 1"],
            visual_queries=["visual 1"],
        )

        selected = ResearchAgent._select_balanced_queries(plan, cap=6)

        assert selected == [
            "cost 1",
            "operations 1",
            "human 1",
            "origin 1",
            "surprise 1",
            "visual 1",
        ]

# ── AngleSynthesisSkill ──────────────────────────────────────────────────────────────

class TestAngleSynthesisSkill:
    @pytest.mark.asyncio
    async def test_run_returns_analysis_result(self, sample_topic):
        from backend.agents._angle_synthesis_skill import (
            AnalysisOutput,
            AngleSynthesisSkill,
            KeyFindingOutput,
            SelectableAngleOutput,
        )

        with patch("backend.agents._angle_synthesis_skill.ChatAnthropic") as MockLLM:
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
                selectable_angles=[
                    SelectableAngleOutput(
                        angle="The chip race became a test of money, scarcity, and timing",
                        framing_axis="data_driven",
                        rationale="It centers the strongest business evidence.",
                    ),
                    SelectableAngleOutput(
                        angle="The human cost behind the AI hardware boom",
                        framing_axis="human_interest",
                        rationale="It frames the same research through worker and customer consequences.",
                    ),
                    SelectableAngleOutput(
                        angle="Why the consensus on AI infrastructure may be too simple",
                        framing_axis="contrarian",
                        rationale="It pushes against the obvious growth narrative.",
                    ),
                ],
                data_gaps=[],
                recommended_tone="investigative",
                controversies=[],
                notable_quotes=[],
                financial_metrics=None,
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            agent = AngleSynthesisSkill()
            package = _make_research_package(sample_topic)
            state = {
                "topic": sample_topic,
                "tone": "investigative",
                "research_package": package,
            }
            result = await agent.run(state)

        assert "analysis_result" in result
        assert "generated_angles" in result
        analysis = result["analysis_result"]
        assert isinstance(analysis, AnalysisResult)
        assert analysis.executive_summary == "AI is booming."
        assert len(analysis.key_findings) == 1
        assert analysis.key_findings[0].supporting_source_ids == [
            package.top_sources(12)[0].source_id
        ]
        assert len(result["generated_angles"]) == 3

    @pytest.mark.asyncio
    async def test_run_uses_fallback_when_llm_fails(self, sample_topic):
        from backend.agents._angle_synthesis_skill import AngleSynthesisSkill

        with patch("backend.agents._angle_synthesis_skill.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.side_effect = ValueError("did not return valid JSON")

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            agent = AngleSynthesisSkill()
            state = {
                "topic": sample_topic,
                "tone": "explanatory",
                "research_package": _make_research_package(),
            }
            result = await agent.run(state)

        assert isinstance(result["analysis_result"], AnalysisResult)
        assert len(result["generated_angles"]) >= 3


# ── PlanReviewSkill ────────────────────────────────────────────────────────────

class TestPlanReviewSkill:
    @pytest.mark.asyncio
    async def test_run_returns_scriptwriter_recommendations(self, sample_topic):
        from backend.agents._chief_editor_plan_review_skill import PlanReviewSkill, PlanReviewOutput

        with patch("backend.agents._chief_editor_plan_review_skill.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = PlanReviewOutput(
                strengths=["Well sourced"],
                weaknesses=[],
                improvement_suggestions=["Clarify the Act 2 turn"],
                scriptwriter_recommendations=["Open with the strongest verified number"],
                research_recommendations=["Avoid naming a company unless source support is explicit"],
                requires_additional_research=False,
                evaluator_notes="Promising direction.",
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            agent = PlanReviewSkill()
            state = {
                "topic": sample_topic,
                "selected_storyline": _make_storyline(),
                "analysis_result": _make_analysis_result(sample_topic),
                "research_package": _make_research_package(sample_topic),
            }
            result = await agent.run(state)

        assert result["needs_more_research"] is False
        assert "approved_for_scripting" not in result
        assert result["evaluation_report"].overall_score is None
        assert result["scriptwriter_recommendations"] == [
            "Open with the strongest verified number",
            "Evidence caution: Avoid naming a company unless source support is explicit",
        ]
        messages = mock_structured.ainvoke.call_args.args[0]
        system_prompt = messages[0].content
        prompt = messages[1].content
        assert "PLAN REVIEW SKILL" in system_prompt
        assert "RECOMMENDATION CALIBRATION" in prompt

    @pytest.mark.asyncio
    async def test_run_falls_back_to_improvement_suggestions(self, sample_topic):
        from backend.agents._chief_editor_plan_review_skill import PlanReviewSkill, PlanReviewOutput

        with patch("backend.agents._chief_editor_plan_review_skill.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = PlanReviewOutput(
                strengths=[],
                weaknesses=["Weak sourcing"],
                improvement_suggestions=["Add more data"],
                requires_additional_research=True,
                evaluator_notes="Needs work.",
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            agent = PlanReviewSkill()
            state = {
                "topic": sample_topic,
                "selected_storyline": _make_storyline(),
                "analysis_result": _make_analysis_result(sample_topic),
                "research_package": _make_research_package(sample_topic),
            }
            result = await agent.run(state)

        assert result["needs_more_research"] is True
        assert result["scriptwriter_recommendations"] == ["Add more data"]


# ── ChapterStructureSkill ─────────────────────────────────────────────────────

class TestChapterStructureSkill:
    @pytest.mark.asyncio
    async def test_run_returns_proposals(self, sample_topic):
        from backend.agents._chapter_structure_skill import (
            StoryActOutput,
            ChapterStructureSkill,
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

        with patch("backend.agents._chapter_structure_skill.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = mock_response

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            agent = ChapterStructureSkill()
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
    async def test_run_enforces_short_duration_act_shape(self, sample_topic):
        from backend.agents._chapter_structure_skill import (
            StoryActOutput,
            ChapterStructureSkill,
            StorylineCreatorOutput,
            StorylineProposalOutput,
        )

        mock_response = StorylineCreatorOutput(
            proposals=[
                StorylineProposalOutput(
                    title="The Short Cut",
                    logline="A compact story.",
                    opening_hook="The hook.",
                    unique_angle="Compressed angle",
                    target_audience="Business viewers",
                    tone="explanatory",
                    acts=[
                        StoryActOutput(
                            act_number=i,
                            act_title=f"Act {i}",
                            purpose=f"Purpose {i}",
                            key_points=[f"Point {i}"],
                            estimated_duration_seconds=120,
                            required_visuals=[f"Visual {i}"],
                        )
                        for i in range(1, 7)
                    ],
                    closing_statement="The payoff.",
                )
            ],
            recommended_proposal_index=0,
        )

        with patch("backend.agents._chapter_structure_skill.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = mock_response

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            result = await ChapterStructureSkill().run({
                "topic": sample_topic,
                "tone": "explanatory",
                "target_duration_minutes": 5,
                "refinement_cycle": 0,
                "analysis_result": _make_analysis_result(sample_topic),
            })

        selected = result["selected_storyline"]
        assert len(selected.acts) == 3
        assert selected.total_estimated_duration_seconds == 300
        assert [act.estimated_duration_seconds for act in selected.acts] == [60, 174, 66]
        prompt = mock_structured.ainvoke.call_args.args[0][1].content
        assert "Requested duration: 5 minutes" in prompt
        assert "never exceed 3 acts" in prompt

    @pytest.mark.asyncio
    async def test_run_uses_deterministic_fallback_after_empty_structured_responses(self, sample_topic):
        from backend.agents._chapter_structure_skill import ChapterStructureSkill

        with patch("backend.agents._chapter_structure_skill.ChatAnthropic") as MockLLM:
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

            agent = ChapterStructureSkill()
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

        with patch("backend.agents.scriptwriter.ChatAnthropic") as MockLLM, \
                patch(
                    "backend.agents.scriptwriter.enrich_if_gaps",
                    new=AsyncMock(return_value=[]),
                ), \
                patch("backend.agents.scriptwriter.ResearchReportSynthesizer") as MockSynth:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = ActOutput(
                narration="AI spending is rising because demand is concentrated in a few suppliers.",
                word_count=12,
                source_ids=[source_id, "unknown-source"],
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base
            MockSynth.return_value.synthesize = AsyncMock(return_value=("", []))

            result = await ScriptwriterAgent().run({
                "story_id": str(uuid.uuid4()),
                "topic": sample_topic,
                "selected_storyline": _make_storyline(),
                "analysis_result": analysis,
                "research_package": package,
                "evaluation_report": None,
                "scriptwriter_recommendations": [
                    "Open with the Chief Editor's strongest verified number."
                ],
                "target_duration_minutes": 15,
                "target_audience": "Business viewers",
            })

        script = result["final_script"]
        assert script.metadata["target_duration_minutes"] == 15
        assert script.metadata["target_audience"] == "Business viewers"
        assert script.metadata["scriptwriter_recommendations"] == [
            "Open with the Chief Editor's strongest verified number."
        ]
        assert all(section.source_ids == [source_id] for section in script.sections)
        assert script.sources[0]["source_id"] == source_id
        # Shared craft/research context lives in the cached system block (a list
        # of content blocks); the per-act spec is in the human message.
        messages = mock_structured.ainvoke.call_args_list[0].args[0]
        def _text(message):
            content = message.content
            if isinstance(content, list):
                return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
            return content
        prompt = _text(messages[0]) + "\n" + _text(messages[1])
        assert "CHIEF EDITOR RECOMMENDATIONS TO APPLY WHILE WRITING" in prompt
        assert "mandatory editorial direction" in prompt
        assert "Requested duration: 15 minutes" in prompt
        assert "Target total word count for the complete script: 2220" in prompt


# ── ScriptAuditSkill ──────────────────────────────────────────────────────────

class TestScriptAuditSkill:
    @pytest.mark.asyncio
    async def test_run_returns_script_audit_report(self, sample_topic):
        from backend.agents._chief_editor_script_audit_skill import ScriptAuditOutput, ScriptAuditSkill
        from backend.models.story import (
            BenchmarkComparison,
            ScriptSectionAudit,
        )

        with patch("backend.agents._chief_editor_script_audit_skill.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = ScriptAuditOutput(
                audit_summary="Strong script with a slightly thin middle section.",
                strengths=["Sharp opening narration"],
                weaknesses=["Act 2 needs more concrete evidence"],
                rewrite_priorities=["Add one specific data point to Act 2"],
                section_audits=[
                    ScriptSectionAudit(
                        section_number=1,
                        title="The Hook",
                        summary="Opens with clear stakes.",
                        strengths=["Immediate tension"],
                        weaknesses=[],
                        benchmark_notes=["Opens in a BI-style high-stakes frame."],
                        rewrite_recommendation="Keep this opening mostly intact.",
                    ),
                    ScriptSectionAudit(
                        section_number=2,
                        title="The Buildout",
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

            agent = ScriptAuditSkill()
            state = {
                "topic": sample_topic,
                "final_script": _make_final_script(),
                "evaluation_report": EvaluationReport(
                    strengths=["Good structure"],
                    weaknesses=["Could use more sourcing"],
                    improvement_suggestions=["Add more specifics"],
                    scriptwriter_recommendations=["Add one visual proof point to Act 2"],
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

            with patch(
                "backend.agents._chief_editor_script_audit_skill.load_active_benchmark_library",
                new=AsyncMock(return_value=(
                    None,
                    BenchmarkLibraryStatus(
                        key="combined",
                        label="Benchmark Corpus",
                        description="",
                        implemented=True,
                        active=True,
                        available=False,
                        ready_for_scoring=False,
                    ),
                )),
            ):
                result = await agent.run(state)

        assert "script_audit_report" in result
        report = result["script_audit_report"]
        assert report.grade is None
        assert report.ready_for_production is None
        assert report.overall_score is None
        assert result["script_rewrite_recommendations"] == ["Add one specific data point to Act 2"]
        assert len(report.section_audits) == 2
        assert report.benchmark_comparison is None
        messages = mock_structured.ainvoke.call_args.args[0]
        system_prompt = messages[0].content
        prompt = messages[1].content
        assert "SCRIPT AUDIT SKILL" in system_prompt
        assert "REWRITE RECOMMENDATION CALIBRATION" in prompt


# ── ScriptRewriteSkill ──────────────────────────────────────────────────────

class TestScriptRewriteSkill:
    @pytest.mark.asyncio
    async def test_run_passes_chief_editor_audit_recommendations_to_rewrite_prompt(self, sample_topic):
        from backend.agents._chief_editor_script_rewrite_skill import RevisedSectionOutput, ScriptRewriteSkill
        from backend.models.story import ScriptAuditReport, ScriptSectionAudit

        with patch("backend.agents._chief_editor_script_rewrite_skill.ChatAnthropic") as MockLLM:
            mock_structured = AsyncMock()
            mock_structured.ainvoke.return_value = RevisedSectionOutput(
                narration="Rewritten narration with a sharper supported detail.",
                source_ids=["source-1"],
            )

            mock_base = MagicMock()
            mock_base.with_structured_output.return_value = mock_structured
            MockLLM.return_value = mock_base

            result = await ScriptRewriteSkill().run({
                "story_id": str(uuid.uuid4()),
                "topic": sample_topic,
                "final_script": _make_final_script(),
                "script_audit_report": ScriptAuditReport(
                    rewrite_priorities=["Add one concrete source-backed number."],
                    section_audits=[
                        ScriptSectionAudit(
                            section_number=1,
                            title="The Hook",
                            summary="Needs sharper specificity.",
                            weaknesses=["Too generic"],
                            rewrite_recommendation="Add a supported number.",
                        ),
                        ScriptSectionAudit(
                            section_number=2,
                            title="The Buildout",
                            summary="Needs a cleaner transition.",
                            weaknesses=["Transition is soft"],
                            rewrite_recommendation="Clarify the cause-effect handoff.",
                        ),
                    ],
                ),
                "analysis_result": _make_analysis_result(sample_topic),
                "research_package": _make_research_package(sample_topic),
                "script_rewrite_recommendations": [
                    "Add one concrete source-backed number."
                ],
                "script_revision_cycle": 0,
                "target_audience": "Business viewers",
            })

        prompt = mock_structured.ainvoke.call_args_list[0].args[0][1].content
        assert "CHIEF EDITOR AUDIT RECOMMENDATIONS TO APPLY IN THIS REWRITE" in prompt
        assert "mandatory rewrite direction" in prompt
