"""
Evaluator Agent — fourth node in the journalist pipeline.

Responsibilities:
  1. Score the selected storyline against six editorial criteria.
  2. Identify strengths and weaknesses with specific, actionable notes.
  3. Decide whether the storyline is ready for scripting or needs refinement.
  4. Flag whether additional research is required.
"""

import json
import re
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.models.research import (
    EvaluationCriteria,
    EvaluationReport,
    StorylineProposal,
)

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are the editorial director of a major video journalism outlet.
You evaluate documentary storylines against professional editorial standards.

Score each criterion from 0.0 (terrible) to 1.0 (publication-ready):
- factual_accuracy: Are all claims well-sourced and verifiable?
- narrative_coherence: Does the story flow logically? Is the structure compelling?
- audience_engagement: Will this hold a viewer's attention for 10-15 minutes?
- source_diversity: Are multiple perspectives and source types represented?
- originality: Does this offer a fresh angle or new insight on the topic?
- production_feasibility: Can this realistically be produced (visuals, interviews)?

Return ONLY valid JSON with this structure:
{
  "criteria": {
    "factual_accuracy": 0.0-1.0,
    "narrative_coherence": 0.0-1.0,
    "audience_engagement": 0.0-1.0,
    "source_diversity": 0.0-1.0,
    "originality": 0.0-1.0,
    "production_feasibility": 0.0-1.0
  },
  "strengths": ["<specific strength>", ...],
  "weaknesses": ["<specific weakness>", ...],
  "improvement_suggestions": ["<actionable suggestion>", ...],
  "requires_additional_research": true|false,
  "additional_research_topics": ["<topic to research further>", ...],
  "evaluator_notes": "<overall editorial assessment in 2-3 sentences>"
}

Be honest and critical. A score below 0.75 overall means the story needs more work.
A score of 0.75 or above means it is ready for scripting."""


class EvaluatorAgent:
    """
    Editorial gatekeeper that scores storylines before they proceed to scripting.

    Example::

        agent = EvaluatorAgent()
        state_updates = await agent.run(state)
    """

    def __init__(self) -> None:
        self._llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=3000,
            temperature=0.1,  # Low temperature for consistent scoring
        )

    async def run(self, state: dict) -> dict:
        """
        Evaluate the selected storyline and produce an EvaluationReport.

        Args:
            state: Current JournalistState with ``selected_storyline`` and
                   ``analysis_result`` populated.

        Returns:
            Partial state update with ``evaluation_report``, ``approved_for_scripting``,
            and ``needs_more_research`` flags.
        """
        storyline: StorylineProposal = state["selected_storyline"]
        analysis = state["analysis_result"]
        topic: str = state["topic"]

        log.info("evaluator.start", topic=topic, title=storyline.title)

        acts_summary = "\n".join(
            f"  Act {a.act_number} ({a.estimated_duration_seconds}s): {a.act_title}\n"
            f"    Purpose: {a.purpose}\n"
            f"    Key points: {', '.join(a.key_points[:3])}"
            for a in storyline.acts
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
            f"=== RESEARCH QUALITY ===\n"
            f"Total Sources: {state['research_package'].total_sources}\n"
            f"Key Findings: {len(analysis.key_findings)}\n"
            f"Data Gaps: {', '.join(analysis.data_gaps) or 'None identified'}\n"
            f"Controversies: {', '.join(analysis.controversies) or 'None identified'}"
        )

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self._llm.ainvoke(messages)
        raw_text: str = response.content

        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            raise ValueError(f"Evaluator LLM returned invalid JSON: {raw_text[:300]}")

        data: dict[str, Any] = json.loads(match.group())

        criteria_data = data.get("criteria", {})
        criteria = EvaluationCriteria(
            factual_accuracy=float(criteria_data.get("factual_accuracy", 0.5)),
            narrative_coherence=float(criteria_data.get("narrative_coherence", 0.5)),
            audience_engagement=float(criteria_data.get("audience_engagement", 0.5)),
            source_diversity=float(criteria_data.get("source_diversity", 0.5)),
            originality=float(criteria_data.get("originality", 0.5)),
            production_feasibility=float(criteria_data.get("production_feasibility", 0.5)),
        )

        report = EvaluationReport(
            criteria=criteria,
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            improvement_suggestions=data.get("improvement_suggestions", []),
            requires_additional_research=data.get("requires_additional_research", False),
            evaluator_notes=data.get("evaluator_notes", ""),
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
        }
