"""
Storyline Creator Agent — third node in the journalist pipeline.

Responsibilities:
  1. Receive structured AnalysisResult from the Analyst.
  2. Generate 2-3 distinct documentary storyline proposals.
  3. Select the strongest proposal as the primary candidate.
  4. Structure each storyline into timed acts that fit a 10–15 minute film.
"""

import json
import re
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.models.research import AnalysisResult, StoryAct, StorylineProposal

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are an award-winning documentary director and story architect.
You create compelling documentary structures in the style of Business Insider, Bloomberg, and CNBC Make It.

Given an editorial analysis, generate exactly 2 storyline proposals for a 10-15 minute documentary.

Return ONLY valid JSON with this structure:
{
  "proposals": [
    {
      "title": "<Working title>",
      "logline": "<One-sentence pitch — the entire story in 25 words>",
      "opening_hook": "<First 30 seconds — the moment that grabs the viewer>",
      "unique_angle": "<What makes this approach different from standard coverage>",
      "target_audience": "<Primary demographic and why they care>",
      "tone": "investigative|explanatory|narrative|profile|trend",
      "acts": [
        {
          "act_number": 1,
          "act_title": "<Act title>",
          "purpose": "<Editorial purpose of this act>",
          "key_points": ["<point>", ...],
          "estimated_duration_seconds": 120,
          "required_visuals": ["<visual/b-roll suggestion>", ...]
        }
      ],
      "closing_statement": "<Final thought / call-to-action for the audience>"
    }
  ],
  "recommended_proposal_index": 0
}

Guidelines:
- Each documentary should have 4-6 acts totalling 600-900 seconds (10-15 min).
- Act 1 (90-120s): Hook & stakes — grab attention, establish why this matters.
- Act 2 (120-180s): Context & history — how did we get here?
- Acts 3-4 (150-180s each): Evidence & exploration — the meat of the story.
- Act 5 (90-120s): Human element — real people, real impact.
- Act 6 (60-90s): Resolution & forward look — what comes next?
- Suggest specific b-roll visuals for each act (stock footage, graphics, interviews).
"""


def _parse_proposals(data: dict[str, Any]) -> tuple[list[StorylineProposal], int]:
    """Convert raw JSON into StorylineProposal Pydantic objects."""
    proposals: list[StorylineProposal] = []
    for p in data.get("proposals", []):
        acts = [
            StoryAct(
                act_number=a["act_number"],
                act_title=a["act_title"],
                purpose=a.get("purpose", ""),
                key_points=a.get("key_points", []),
                estimated_duration_seconds=a.get("estimated_duration_seconds", 120),
                required_visuals=a.get("required_visuals", []),
            )
            for a in p.get("acts", [])
        ]
        proposal = StorylineProposal(
            title=p["title"],
            logline=p.get("logline", ""),
            opening_hook=p.get("opening_hook", ""),
            acts=acts,
            closing_statement=p.get("closing_statement", ""),
            unique_angle=p.get("unique_angle", ""),
            target_audience=p.get("target_audience", "general audience"),
            tone=p.get("tone", "explanatory"),
        )
        proposal.compute_duration()
        proposals.append(proposal)

    recommended_idx = int(data.get("recommended_proposal_index", 0))
    recommended_idx = min(recommended_idx, len(proposals) - 1)
    return proposals, recommended_idx


class StorylineCreatorAgent:
    """
    Documentary structure designer that builds multi-act storyline proposals.

    Example::

        agent = StorylineCreatorAgent()
        state_updates = await agent.run(state)
    """

    def __init__(self) -> None:
        self._llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=6000,
            temperature=0.5,  # Higher temperature for creative diversity
        )

    async def run(self, state: dict) -> dict:
        """
        Execute the storyline creation phase.

        Args:
            state: Current JournalistState with ``analysis_result`` populated.

        Returns:
            Partial state update with ``storyline_proposals`` and ``selected_storyline``.
        """
        analysis: AnalysisResult = state["analysis_result"]
        topic: str = state["topic"]
        tone: str = state.get("tone", analysis.recommended_tone)
        refinement_cycle: int = state.get("refinement_cycle", 0)

        # If we're in a refinement cycle, include evaluator feedback
        evaluation_feedback = ""
        if refinement_cycle > 0 and state.get("evaluation_report"):
            ev = state["evaluation_report"]
            evaluation_feedback = (
                f"\n\nPREVIOUS EVALUATION FEEDBACK (cycle {refinement_cycle}):\n"
                f"Overall score: {ev.overall_score:.2f}\n"
                f"Weaknesses: {chr(10).join(ev.weaknesses)}\n"
                f"Suggestions: {chr(10).join(ev.improvement_suggestions)}\n"
                f"Address these issues in the new proposals."
            )

        log.info("storyline_creator.start", topic=topic, refinement_cycle=refinement_cycle)

        prompt = (
            f"Topic: {topic}\n"
            f"Target tone: {tone}\n"
            f"Target duration: {settings.target_script_duration_min}–{settings.target_script_duration_max} minutes\n\n"
            f"=== EDITORIAL ANALYSIS ===\n"
            f"Executive Summary: {analysis.executive_summary}\n\n"
            f"Key Findings:\n"
            + "\n".join(f"  - [{f.category}] {f.claim}" for f in analysis.key_findings[:10])
            + f"\n\nNarrative Angles:\n"
            + "\n".join(f"  - {a}" for a in analysis.narrative_angles)
            + f"\n\nNotable Quotes:\n"
            + "\n".join(
                f"  - \"{q.get('quote', '')}\" — {q.get('speaker', '')}"
                for q in analysis.notable_quotes[:5]
            )
            + evaluation_feedback
        )

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self._llm.ainvoke(messages)
        raw_text: str = response.content

        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            raise ValueError(f"StorylineCreator LLM returned invalid JSON: {raw_text[:300]}")

        data = json.loads(match.group())
        proposals, recommended_idx = _parse_proposals(data)

        if not proposals:
            raise ValueError("StorylineCreator produced no proposals.")

        selected = proposals[recommended_idx]

        log.info(
            "storyline_creator.complete",
            topic=topic,
            proposals=len(proposals),
            selected_title=selected.title,
            duration_s=selected.total_estimated_duration_seconds,
        )

        return {
            "storyline_proposals": proposals,
            "selected_storyline": selected,
        }
