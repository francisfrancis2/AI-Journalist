"""
Evaluator Agent — fourth node in the journalist pipeline.

Responsibilities:
  1. Score the selected storyline against six editorial criteria.
  2. Identify strengths and weaknesses with specific, actionable notes.
  3. Decide whether the storyline is ready for scripting or needs refinement.
  4. Flag whether additional research is required.
"""

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import (
    EvaluationCriteria,
    EvaluationReport,
    StorylineProposal,
)
from backend.services.library_knowledge import (
    format_reference_pack,
    get_reference_pack,
    merge_reference_pack,
)
from backend.services.prompt_loader import load_prompt

log = structlog.get_logger(__name__)


# ── Structured output schema ──────────────────────────────────────────────────

class CriteriaOutput(BaseModel):
    factual_accuracy: float = Field(ge=0.0, le=1.0)
    narrative_coherence: float = Field(ge=0.0, le=1.0)
    audience_engagement: float = Field(ge=0.0, le=1.0)
    source_diversity: float = Field(ge=0.0, le=1.0)
    originality: float = Field(ge=0.0, le=1.0)
    production_feasibility: float = Field(ge=0.0, le=1.0)


class EvaluatorOutput(BaseModel):
    criteria: CriteriaOutput
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    requires_additional_research: bool = False
    evaluator_notes: str = ""


# ── Editable prompt loaded from backend/prompts ──────────────────────────────



class EvaluatorAgent:
    """
    Editorial gatekeeper that scores storylines before they proceed to scripting.

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
                "Use this to identify precise gaps versus the reference-library standard. "
                "Do not reveal source channels or reference titles.\n\n"
            )

        prompt = (
            f"Topic: {topic}\n"
            f"Storyline Title: {storyline.title}\n"
            f"Logline: {storyline.logline}\n"
            f"Unique Angle: {storyline.unique_angle}\n"
            f"Target Audience: {storyline.target_audience}\n"
            f"Tone: {storyline.tone}\n"
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

        criteria = EvaluationCriteria(
            factual_accuracy=output.criteria.factual_accuracy,
            narrative_coherence=output.criteria.narrative_coherence,
            audience_engagement=output.criteria.audience_engagement,
            source_diversity=output.criteria.source_diversity,
            originality=output.criteria.originality,
            production_feasibility=output.criteria.production_feasibility,
        )

        report = EvaluationReport(
            criteria=criteria,
            strengths=output.strengths,
            weaknesses=output.weaknesses,
            improvement_suggestions=output.improvement_suggestions,
            requires_additional_research=output.requires_additional_research,
            evaluator_notes=output.evaluator_notes,
        )
        report.compute_overall()

        log.info(
            "evaluator.complete",
            topic=topic,
            overall_score=f"{report.overall_score:.2f}",
            approved=report.approved_for_scripting,
            needs_research=report.requires_additional_research,
        )

        return {
            "evaluation_report": report,
            "approved_for_scripting": report.approved_for_scripting,
            "needs_more_research": report.requires_additional_research,
            "reference_packs": merge_reference_pack(state, reference_pack),
        }
