"""
ScriptEvaluatorAgent — post-script audit for the finished documentary script.

This agent runs after ScriptwriterAgent and inspects the final script itself,
not just the storyline. It produces section-level notes, rewrite priorities,
and best-practice comparison notes when benchmark context is available.
"""

from typing import Optional

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.benchmark import BIPatternLibrary
from backend.models.story import (
    BenchmarkComparison,
    FinalScript,
    ScriptAuditReport,
    ScriptSectionAudit,
)
from backend.services.benchmarking import load_active_benchmark_library
from backend.services.library_knowledge import (
    format_reference_pack,
    get_reference_pack,
    merge_reference_pack,
)
from backend.services.prompt_loader import load_prompt

log = structlog.get_logger(__name__)



class ScriptAuditOutput(BaseModel):
    """Structured rewrite recommendations returned by the LLM."""

    audit_summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    rewrite_priorities: list[str] = Field(default_factory=list)
    section_audits: list[ScriptSectionAudit] = Field(default_factory=list)
    benchmark_comparison: Optional[BenchmarkComparison] = None


class ScriptEvaluatorAgent:
    """
    Final-script auditor that turns script feedback into rewriter guidance.

    Example::

        agent = ScriptEvaluatorAgent()
        result = await agent.run(state)
    """

    def __init__(self) -> None:
        # Claude Opus 4.7 is a reasoning model and rejects the `temperature`
        # argument at the API layer; omit it (matches scriptwriter config).
        _llm = ChatAnthropic(
            model=settings.claude_opus_model,
            api_key=settings.anthropic_api_key,
            max_tokens=2500,
        )
        self._structured_llm = _llm.with_structured_output(ScriptAuditOutput)

    @staticmethod
    def _format_sections(script: FinalScript) -> str:
        return "\n\n".join(
            (
                f"Section {section.section_number}: {section.title}\n"
                f"Estimated seconds: {section.estimated_seconds}\n"
                f"Source IDs: {', '.join(section.source_ids) or 'None'}\n"
                f"Narration:\n{section.narration}"
            )
            for section in script.sections
        )

    @staticmethod
    def _format_sources(script: FinalScript) -> str:
        if not script.sources:
            return "No source references attached."
        return "\n".join(
            f"- {src.get('source_id', 'unlinked')} [{src.get('credibility', 'medium').upper()}] {src.get('title', 'Untitled')}"
            f"{' (' + str(src.get('type')) + ')' if src.get('type') else ''}"
            f"{' — ' + str(src.get('url')) if src.get('url') else ''}"
            for src in script.sources[:12]
        )

    @staticmethod
    def _format_storyline_feedback(state: dict) -> str:
        evaluation = state.get("evaluation_report")
        benchmark = state.get("benchmark_report")

        sections: list[str] = []
        if evaluation:
            recommendation_text = ", ".join(
                evaluation.scriptwriter_recommendations
                or evaluation.improvement_suggestions
                or []
            ) or "None"
            sections.append(
                "Pre-script editorial evaluation:\n"
                f"- Strengths: {', '.join(evaluation.strengths) or 'None'}\n"
                f"- Weaknesses: {', '.join(evaluation.weaknesses) or 'None'}\n"
                f"- Scriptwriter recommendations: {recommendation_text}"
            )
        if benchmark:
            sections.append(
                "Pre-script benchmark:\n"
                f"- Gaps: {', '.join(benchmark.gaps) or 'None'}\n"
                f"- Strengths: {', '.join(benchmark.strengths) or 'None'}"
            )

        return "\n\n".join(sections) if sections else "No prior editorial feedback available."

    @staticmethod
    def _format_benchmark_context(library: Optional[BIPatternLibrary]) -> str:
        if not library:
            return "Benchmark context unavailable. Set benchmark_comparison to null."

        sample_hooks = "\n".join(f"- {hook}" for hook in library.sample_hooks[:5]) or "- None"

        return (
            "Benchmark context available:\n"
            f"- Corpus size: {library.doc_count} reference documentaries\n"
            f"- Average act count: {library.avg_act_count:.1f}\n"
            f"- Average act duration: {library.avg_act_duration_seconds:.0f}s\n"
            f"- Average stats per documentary: {library.avg_stat_count:.1f}\n"
            f"- Typical human-story act: {library.human_story_act_avg:.1f}\n"
            f"- Hook distribution: {library.hook_type_distribution}\n"
            f"- Title distribution: {library.title_formula_distribution}\n"
            f"- Closing distribution: {library.closing_device_distribution}\n"
            "Sample opening hooks:\n"
            f"{sample_hooks}"
        )

    @staticmethod
    def _normalise_section_audits(
        script: FinalScript,
        audits: list[ScriptSectionAudit],
    ) -> list[ScriptSectionAudit]:
        """Ensure every script section gets an audit entry, even if the model omits one."""
        audit_by_number = {audit.section_number: audit for audit in audits}
        normalised: list[ScriptSectionAudit] = []

        for section in script.sections:
            existing = audit_by_number.get(section.section_number)
            if existing:
                normalised.append(existing.model_copy(update={"score": None}))
                continue

            normalised.append(
                ScriptSectionAudit(
                    section_number=section.section_number,
                    title=section.title,
                    summary="This section was not individually audited by the model.",
                    strengths=[],
                    weaknesses=["Missing section-level audit output."],
                    benchmark_notes=[],
                    rewrite_recommendation="Review this section manually and tighten its narrative purpose.",
                )
            )

        return normalised

    async def run(self, state: dict) -> dict:
        """
        Audit the final script and return a persisted ScriptAuditReport.

        This is a post-processing step. If it fails upstream callers should treat
        the audit as optional and preserve the generated script.
        """
        script: FinalScript | None = state.get("final_script")
        if script is None:
            raise ValueError("script_evaluator received no final_script")

        topic: str = state["topic"]
        library, library_status = await load_active_benchmark_library()
        reference_pack = get_reference_pack(
            role="script_evaluator",
            topic=topic,
            state=state,
            max_cards=5,
            token_budget=1500,
        )
        reference_context = format_reference_pack(reference_pack)
        reference_section = ""
        if reference_context:
            reference_section = (
                f"\n=== SCRIPT AUDIT LIBRARY REFERENCE ===\n{reference_context}\n"
                "Use this to produce rewrite recommendations from learned best practices. "
                "Do not reveal source channels or reference titles.\n"
                "\n=== REWRITE RECOMMENDATION CALIBRATION ===\n"
                "Do not assign scores. Compare the written script to the best-practice patterns "
                "in the library reference pack and convert gaps into executable rewrite priorities. "
                "Cover hook shape, evidence density, narration flow, pacing, write-for-the-ear "
                "cadence, visual practicality, source support, and closing payoff when relevant. "
                "Every rewrite_priority and section rewrite_recommendation must tell the "
                "ScriptRewriter exactly what to preserve, cut, add, strengthen, or verify.\n"
            )

        prompt = (
            f"Topic: {topic}\n"
            f"Script title: {script.title}\n"
            f"Logline: {script.logline}\n"
            f"Opening hook: {script.opening_hook}\n"
            f"Closing statement: {script.closing_statement}\n"
            f"Estimated duration: {script.estimated_duration_minutes} minutes\n"
            f"Total word count: {script.total_word_count}\n"
            f"\n=== FINAL SCRIPT ===\n{self._format_sections(script)}\n\n"
            f"=== SOURCE REFS ===\n{self._format_sources(script)}\n\n"
            f"=== PRIOR FEEDBACK ===\n{self._format_storyline_feedback(state)}\n\n"
            f"{reference_section}"
            f"=== BENCHMARK CONTEXT ===\n{self._format_benchmark_context(library)}"
        )

        log.info(
            "script_evaluator.start",
            title=script.title,
            sections=len(script.sections),
            benchmark_available=library is not None,
            benchmark_notes=library_status.notes,
        )

        output: ScriptAuditOutput = await self._structured_llm.ainvoke([
            SystemMessage(content=load_prompt("script_evaluator")),
            HumanMessage(content=prompt),
        ])

        report = ScriptAuditReport(
            audit_summary=output.audit_summary,
            strengths=output.strengths,
            weaknesses=output.weaknesses,
            rewrite_priorities=output.rewrite_priorities,
            section_audits=self._normalise_section_audits(script, output.section_audits),
            benchmark_comparison=output.benchmark_comparison if library else None,
        )

        log.info(
            "script_evaluator.complete",
            title=script.title,
            rewrite_priorities=len(report.rewrite_priorities),
        )

        return {
            "script_audit_report": report,
            "script_rewriter_recommendations": report.rewrite_priorities,
            "reference_packs": merge_reference_pack(state, reference_pack),
        }
