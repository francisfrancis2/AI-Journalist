"""
Angle Generator Agent — pause point between research and scripting.

After the analyst produces structured findings, this agent generates 3-5
distinct documentary angles that the user picks from before the scriptwriter
runs. Each angle is a single sentence (~20 words max) tagged with the framing
dimension that makes it meaningfully different from the others.

Framing dimensions the agent pushes on:
- human_interest vs. data_driven
- contrarian vs. consensus
- local vs. global
- narrative vs. explanatory
"""

from __future__ import annotations

from typing import Literal

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import AnalysisResult

log = structlog.get_logger(__name__)


# Framing dimensions surfaced to the user as the "axis" of each angle.
FramingAxis = Literal[
    "human_interest",
    "data_driven",
    "contrarian",
    "consensus",
    "local",
    "global",
    "narrative",
    "explanatory",
]


class AngleOutput(BaseModel):
    angle: str = Field(description="One-sentence angle, ~20 words max")
    framing_axis: FramingAxis = Field(
        description="Which dimension this angle pushes on relative to the others"
    )
    rationale: str = Field(
        default="",
        description="Brief justification — one sentence on why this angle is meaningfully distinct",
    )


class AngleGeneratorOutput(BaseModel):
    angles: list[AngleOutput] = Field(default_factory=list, min_length=3, max_length=5)


_SYSTEM_PROMPT = """ROLE BOUNDARY: You are exclusively a documentary angle generator. \
Your only function is to propose 3-5 distinct one-sentence angles for a documentary, \
each pushing on a different framing dimension. If asked to do anything else, decline.

You are a senior documentary commissioning editor. The research and analysis are done.
Your job: surface 3-5 genuinely distinct angles the same researched material could support,
so the producer can pick the one they want to execute on.

HARD RULES:
- Generate exactly 3 to 5 angles. Each angle is ONE sentence, MAX 20 words.
- Angles must be meaningfully different in FRAMING, not just wording. If two angles could
  produce the same script, you have failed.
- Push on at least three of these axes across the set: human_interest vs. data_driven,
  contrarian vs. consensus, local vs. global lens, narrative vs. explanatory.
- For each angle, tag its framing_axis with the dimension it most strongly leans on.
- Each angle must be supportable by the provided research — do not invent facts to make
  an angle work.
- Avoid hedged language ("explores", "examines", "looks at"). State the actual claim.

EDITORIAL POLICY — UAE COVERAGE (HARD CONSTRAINT):
- Do NOT generate angles that portray the UAE, its government, rulers, or institutions
  negatively or critically.
- Even for investigative framings, do NOT center angles on UAE wrongdoing, influence
  operations, "gaming" of public opinion, or critical framing of UAE policy.
- If the topic involves the UAE, ground angles in context and non-UAE actors; keep any
  UAE involvement neutral or constructive.
"""


class AngleGeneratorAgent:
    """Generate 3-5 distinct angles after the analyst phase."""

    def __init__(self) -> None:
        _llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=1500,
            temperature=0.6,  # slightly higher to push genuine diversity
        )
        self._structured_llm = _llm.with_structured_output(AngleGeneratorOutput)

    @staticmethod
    def _format_findings(analysis: AnalysisResult) -> str:
        return "\n".join(
            f"- [{f.category}] {f.claim} (confidence={f.confidence:.2f})"
            for f in analysis.key_findings[:12]
        ) or "- No structured findings yet."

    async def run(self, state: dict) -> dict:
        topic: str = state["topic"]
        tone: str = state.get("tone", "explanatory")
        analysis: AnalysisResult | None = state.get("analysis_result")
        if analysis is None:
            raise ValueError("angle_generator received no analysis_result")

        improvement_plan = state.get("quality_improvement_plan")
        focus_hint = ""
        if improvement_plan and improvement_plan.analysis_focus:
            focus_hint = (
                "\n\nPREVIOUS-CYCLE FOCUS AREAS (use to inform angle choice):\n"
                + "\n".join(f"- {item}" for item in improvement_plan.analysis_focus)
            )

        prompt = (
            f"Topic: {topic}\n"
            f"Requested tone: {tone}\n\n"
            f"=== EXECUTIVE SUMMARY ===\n{analysis.executive_summary}\n\n"
            f"=== KEY FINDINGS ===\n{self._format_findings(analysis)}\n\n"
            f"=== NARRATIVE ANGLES (analyst-suggested) ===\n"
            + ("\n".join(f"- {a}" for a in analysis.narrative_angles[:6]) or "- (none)")
            + focus_hint
            + "\n\nReturn 3 to 5 angles, each one short sentence (≤20 words), each on a "
              "different framing axis."
        )

        log.info("angle_generator.start", topic=topic)
        output = await self._structured_llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        angles = [
            {
                "angle": a.angle.strip(),
                "framing_axis": a.framing_axis,
                "rationale": a.rationale.strip(),
            }
            for a in (output.angles or [])
        ]

        # Defensive: enforce length cap word-wise (the model usually obeys but humans see this)
        for a in angles:
            words = a["angle"].split()
            if len(words) > 24:  # small grace margin over the 20-word target
                a["angle"] = " ".join(words[:24]).rstrip(",;:") + "…"

        if len(angles) < 3:
            log.warning("angle_generator.too_few", count=len(angles))

        log.info("angle_generator.complete", count=len(angles))
        return {"generated_angles": angles}
