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

import json
import random
from pathlib import Path
from typing import Literal

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import AnalysisResult
from backend.services.prompt_loader import load_prompt

log = structlog.get_logger(__name__)


# ── Corpus inspiration ────────────────────────────────────────────────────────
# Pulls real titles and dominant title formulas from the YouTube benchmark
# libraries so the angle generator can learn published documentary framings
# rather than guess at conventions. All four cached corpora contribute.

_LIBRARY_LABELS: dict[str, str] = {
    "bi":   "Business Insider",
    "cnbc": "CNBC Make It",
    "vox":  "Vox",
    "jh":   "Johnny Harris",
}


def _load_corpus_inspiration(
    *,
    per_library_titles: int = 5,
    per_library_formulas: int = 2,
) -> str:
    """
    Load sample titles + top title formulas from each benchmark library and
    format them as a reference block. Returns "" if no caches are present.

    Sampling is randomised per call so successive generations see different
    titles (useful when the user clicks Regenerate angles).
    """
    parts: list[str] = []
    for key, label in _LIBRARY_LABELS.items():
        path = Path(settings.get_pattern_cache_path(key))
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("angle_generator.pattern_load_failed", key=key, error=str(exc))
            continue

        titles: list[str] = data.get("sample_titles") or []
        formula_dist: dict[str, float] = data.get("title_formula_distribution") or {}
        if not titles and not formula_dist:
            continue

        sampled = (
            random.sample(titles, min(per_library_titles, len(titles))) if titles else []
        )
        top_formulas = sorted(
            formula_dist.items(), key=lambda kv: kv[1], reverse=True
        )[:per_library_formulas]

        block: list[str] = [f"-- {label} ({data.get('doc_count', '?')} docs) --"]
        if top_formulas:
            block.append("Title formulas: " + " | ".join(name for name, _ in top_formulas))
        if sampled:
            block.append("Example titles:")
            block.extend(f"  • {t}" for t in sampled)
        parts.append("\n".join(block))

    return "\n\n".join(parts)


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

        corpus_inspiration = _load_corpus_inspiration()
        inspiration_section = ""
        if corpus_inspiration:
            inspiration_section = (
                "\n\n=== REFERENCE FRAMINGS (proven on published documentaries) ===\n"
                + corpus_inspiration
                + "\n\nThese are FRAMING inspiration only — never copy the wording. "
                  "Your angles must be specific to the topic above and span different axes."
            )

        prompt = (
            f"Topic: {topic}\n"
            f"Requested tone: {tone}\n\n"
            f"=== EXECUTIVE SUMMARY ===\n{analysis.executive_summary}\n\n"
            f"=== KEY FINDINGS ===\n{self._format_findings(analysis)}\n\n"
            f"=== NARRATIVE ANGLES (analyst-suggested) ===\n"
            + ("\n".join(f"- {a}" for a in analysis.narrative_angles[:6]) or "- (none)")
            + focus_hint
            + inspiration_section
            + "\n\nReturn 3 to 5 angles, each one short sentence (≤20 words), each on a "
              "different framing axis."
        )

        log.info("angle_generator.start", topic=topic)
        output = await self._structured_llm.ainvoke([
            SystemMessage(content=load_prompt("angle_generator")),
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
