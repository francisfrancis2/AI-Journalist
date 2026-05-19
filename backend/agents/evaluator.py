"""
Evaluator Agent — fourth node in the journalist pipeline.

Responsibilities:
  1. Review the selected storyline against editorial best practices.
  2. Identify strengths and weaknesses with specific, actionable notes.
  3. Pass concrete improvement recommendations to the Scriptwriter.
  4. Flag evidence gaps the Scriptwriter should handle carefully.
"""

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import EvaluationReport, StorylineProposal
from backend.services.library_knowledge import (
    format_reference_pack,
    get_reference_pack,
    merge_reference_pack,
)
from backend.services.duration_targets import duration_prompt_block, duration_target_for
from backend.services.prompt_loader import load_prompt

log = structlog.get_logger(__name__)


class EvaluatorOutput(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    scriptwriter_recommendations: list[str] = Field(default_factory=list)
    research_recommendations: list[str] = Field(default_factory=list)
    requires_additional_research: bool = False
    evaluator_notes: str = ""


# ── Editable prompt loaded from backend/prompts ──────────────────────────────



class EvaluatorAgent:
    """
    Editorial reviewer that turns storyline feedback into scriptwriter guidance.

    Example::

        agent = EvaluatorAgent()
        state_updates = await agent.run(state)
    """

    def __init__(self) -> None:
        _llm = ChatAnthropic(
            model=settings.claude_haiku_model,
            api_key=settings.anthropic_api_key,
            max_tokens=1500,
            temperature=0.1,
        )
        self._structured_llm = _llm.with_structured_output(EvaluatorOutput)

    async def run(self, state: dict) -> dict:
        storyline: StorylineProposal | None = state.get("selected_storyline")
        if storyline is None:
            raise ValueError(
                "evaluator received no storyline — storyline_creator likely failed upstream"
            )

        analysis = state["analysis_result"]
        topic: str = state["topic"]
        duration_target = duration_target_for(state.get("target_duration_minutes"))

        log.info("evaluator.start", topic=topic, title=storyline.title)

        acts_summary = "\n".join(
            f"  Act {a.act_number} ({a.estimated_duration_seconds}s): {a.act_title}\n"
            f"    Purpose: {a.purpose}\n"
            f"    Key points: {', '.join(a.key_points[:3])}"
            for a in storyline.acts
        )
        reference_pack = get_reference_pack(
            role="evaluator",
            topic=topic,
            state=state,
            max_cards=4,
            token_budget=1200,
        )
        reference_section = ""
        reference_context = format_reference_pack(reference_pack)
        if reference_context:
            reference_section = (
                f"\n=== LIBRARY EVALUATION REFERENCE ===\n{reference_context}\n"
                "Use this to produce concrete scriptwriter recommendations from learned best "
                "practices. Do not reveal source channels or reference titles.\n\n"
                "=== RECOMMENDATION CALIBRATION ===\n"
                "Do not assign scores. Instead, compare the storyline to the best-practice "
                "patterns in the library reference pack and convert any gap into an executable "
                "recommendation for the scriptwriter. Cover hook shape, evidence density, "
                "human element, act architecture, visual proof, transitions, and closing payoff "
                "when relevant. Recommendations must tell the scriptwriter exactly what to "
                "preserve, strengthen, add, avoid, or verify.\n\n"
            )

        prompt = (
            f"Topic: {topic}\n"
            f"Storyline Title: {storyline.title}\n"
            f"Logline: {storyline.logline}\n"
            f"Unique Angle: {storyline.unique_angle}\n"
            f"Target Audience: {storyline.target_audience}\n"
            f"Tone: {storyline.tone}\n"
            f"{duration_prompt_block(duration_target, role='Evaluator')}"
            f"Requested act count range: {duration_target.act_count_label}; "
            f"actual act count: {len(storyline.acts)}.\n"
            f"Total Duration: {storyline.total_estimated_duration_seconds // 60} min "
            f"{storyline.total_estimated_duration_seconds % 60} sec\n\n"
            f"Opening Hook: {storyline.opening_hook}\n\n"
            f"Acts:\n{acts_summary}\n\n"
            f"Closing Statement: {storyline.closing_statement}\n\n"
            f"{reference_section}"
            f"=== RESEARCH QUALITY ===\n"
            f"Total Sources: {state['research_package'].total_sources}\n"
            f"Key Findings: {len(analysis.key_findings)}\n"
            f"Data Gaps: {', '.join(analysis.data_gaps) or 'None identified'}\n"
            f"Controversies: {', '.join(analysis.controversies) or 'None identified'}"
        )

        output: EvaluatorOutput = await self._structured_llm.ainvoke([
            SystemMessage(content=load_prompt("evaluator")),
            HumanMessage(content=prompt),
        ])

        scriptwriter_recommendations = list(
            output.scriptwriter_recommendations
            or output.improvement_suggestions
            or output.weaknesses
        )
        scriptwriter_recommendations.extend(
            f"Evidence caution: {item}" for item in output.research_recommendations
        )

        report = EvaluationReport(
            strengths=output.strengths,
            weaknesses=output.weaknesses,
            improvement_suggestions=output.improvement_suggestions,
            scriptwriter_recommendations=scriptwriter_recommendations,
            research_recommendations=output.research_recommendations,
            requires_additional_research=output.requires_additional_research,
            evaluator_notes=output.evaluator_notes,
        )

        log.info(
            "evaluator.complete",
            topic=topic,
            recommendations=len(scriptwriter_recommendations),
            needs_research=report.requires_additional_research,
        )

        return {
            "evaluation_report": report,
            "scriptwriter_recommendations": scriptwriter_recommendations,
            "needs_more_research": report.requires_additional_research,
            "reference_packs": merge_reference_pack(state, reference_pack),
        }
