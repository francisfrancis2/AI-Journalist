"""
Analyst Agent — second node in the journalist pipeline.

Responsibilities:
  1. Receive the ResearchPackage from the Researcher.
  2. Identify key findings, narrative angles, data gaps, and notable quotes.
  3. Generate 3-5 distinct producer-selectable documentary angles.
  4. Detect financial metrics and controversial elements.
  5. Produce structured state that the Storyline Creator can use after angle selection.
"""

from typing import Literal, Optional

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import (
    AnalysisResult,
    KeyFinding,
    ResearchPackage,
)
from backend.services.library_knowledge import (
    format_reference_pack,
    get_reference_pack,
    merge_reference_pack,
)
from backend.services.duration_targets import duration_prompt_block, duration_target_for
from backend.services.prompt_loader import load_prompt

log = structlog.get_logger(__name__)


# ── Structured output schemas ─────────────────────────────────────────────────

class KeyFindingOutput(BaseModel):
    claim: str
    supporting_sources: list[str] = Field(default_factory=list)
    supporting_source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    category: str = Field(
        default="general",
        description=(
            "One of: numeric_anchor | process_step | protagonist | origin_event | "
            "counterintuitive | visual_artifact | quotable | general"
        ),
    )


class QuoteOutput(BaseModel):
    quote: str
    speaker: str
    source: str = ""


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


class SelectableAngleOutput(BaseModel):
    angle: str = Field(description="One-sentence documentary angle, ~20 words max")
    framing_axis: FramingAxis = Field(
        description="Which framing dimension this angle most strongly pushes on"
    )
    rationale: str = Field(
        default="",
        description="One sentence explaining why this angle is meaningfully distinct",
    )


class AnalysisOutput(BaseModel):
    executive_summary: str
    key_findings: list[KeyFindingOutput]
    narrative_angles: list[str] = Field(default_factory=list)
    selectable_angles: list[SelectableAngleOutput] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    recommended_tone: str = "explanatory"
    controversies: list[str] = Field(default_factory=list)
    notable_quotes: list[QuoteOutput] = Field(default_factory=list)
    financial_metrics: Optional[dict[str, str]] = None


# ── Editable prompt loaded from backend/prompts ──────────────────────────────


_MAX_SOURCE_CHARS = 30_000

# Tone simplification: investigative absorbs "trend", narrative absorbs "profile".
# Defensive — the prompt already restricts the model, but older fixtures or stale
# context can still echo the old values.
_TONE_REMAP = {"trend": "investigative", "profile": "narrative"}
_ALLOWED_TONES = {"investigative", "explanatory", "narrative"}


def _normalize_tone(value: str) -> str:
    v = (value or "").strip().lower()
    v = _TONE_REMAP.get(v, v)
    return v if v in _ALLOWED_TONES else "explanatory"


def _build_source_digest(package: ResearchPackage) -> str:
    lines: list[str] = []
    for i, src in enumerate(package.top_sources(12), 1):
        credibility_tag = f"[{src.credibility.value.upper()}]"
        lines.append(
            f"--- SOURCE {i} {credibility_tag} ---\n"
            f"Source ID: {src.source_id}\n"
            f"Title: {src.title}\n"
            f"URL: {src.url or 'N/A'}\n"
            f"Content: {src.content[:800]}\n"
        )
    return "\n".join(lines)[:_MAX_SOURCE_CHARS]




class AnalystAgent:
    """
    Editorial analyst that transforms raw research into structured insights.

    Example::

        agent = AnalystAgent()
        state_updates = await agent.run(state)
    """

    def __init__(self) -> None:
        # Claude Opus 4.7 is a reasoning model and rejects the `temperature`
        # argument at the API layer; omit it (matches scriptwriter config).
        _llm = ChatAnthropic(
            model=settings.claude_opus_model,
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
        )
        self._structured_llm = _llm.with_structured_output(AnalysisOutput)

    @staticmethod
    def _build_fallback_output(topic: str, package: ResearchPackage) -> AnalysisOutput:
        """Minimal analysis built directly from source titles/content when the LLM fails."""
        top = package.top_sources(8)
        findings = [
            KeyFindingOutput(
                claim=src.title or src.content[:120],
                supporting_sources=[src.url or src.title or ""],
                supporting_source_ids=[src.source_id],
                confidence=src.relevance_score,
                category="general",
            )
            for src in top[:6]
            if src.title or src.content
        ] or [KeyFindingOutput(claim=f"Research gathered on: {topic}", confidence=0.5, category="general")]
        return AnalysisOutput(
            executive_summary=f"Research analysis for: {topic}. Based on {package.total_sources} sources.",
            key_findings=findings,
            narrative_angles=[f"Exploring {topic} through available evidence"],
            selectable_angles=[
                SelectableAngleOutput(
                    angle=f"How {topic} became a story of money, risk, and timing",
                    framing_axis="explanatory",
                    rationale="Uses the available research to frame the topic as a clear cause-and-effect documentary.",
                ),
                SelectableAngleOutput(
                    angle=f"The human stakes behind {topic}",
                    framing_axis="human_interest",
                    rationale="Pulls the story toward people affected by the topic.",
                ),
                SelectableAngleOutput(
                    angle=f"What the numbers reveal about {topic}",
                    framing_axis="data_driven",
                    rationale="Centers the strongest sourced metrics and verifiable claims.",
                ),
            ],
            data_gaps=["Further primary sources would strengthen this story"],
            recommended_tone="explanatory",
            controversies=[],
            notable_quotes=[],
        )

    async def run(self, state: dict) -> dict:
        package: ResearchPackage = state["research_package"]
        topic: str = state["topic"]
        tone: str = state.get("tone", "explanatory")
        duration_target = duration_target_for(state.get("target_duration_minutes"))

        log.info("analyst.start", topic=topic, source_count=package.total_sources)

        gap_section = ""
        focus_section = ""

        reference_pack = get_reference_pack(
            role="analyst",
            topic=topic,
            state=state,
            max_cards=6,
            token_budget=1700,
        )
        inspiration_section = ""
        reference_context = format_reference_pack(reference_pack)
        if reference_context:
            inspiration_section = (
                "\n"
                + reference_context
                + "\nUse the pack to calibrate fact density and selectable angle shape. "
                  "Do not copy examples or treat them as source material.\n"
            )

        voice_section = ""
        if settings.enable_team_voice_profile:
            voice_section = (
                "\n=== TEAM VOICE PROFILE (wording polish only) ===\n"
                "You are about to generate key_findings and selectable_angles. Use the "
                "TEAM VOICE PROFILE below to shape HOW you phrase angle text and finding "
                "claims — the contrast pairs, definitional reframes, signature pivots, "
                "and specific-named-referents-over-generics rules apply to wording.\n\n"
                "CRITICAL — voice does NOT override substance:\n"
                "- Library knowledge and corpus inspiration (above) tell you WHAT makes a "
                "strong angle for this topic. The voice profile only tells you HOW to "
                "phrase the angle once you've identified it. If the two conflict, the "
                "library and the actual research win.\n"
                "- Do NOT invent angles that aren't supported by the research package in "
                "order to fit a voice device. A clever contrast pair with no supporting "
                "source is a worse angle than a plain one that does.\n"
                "- recommended_tone and framing_axis classifications are unchanged by "
                "voice — those are categorical, not stylistic.\n\n"
                "Apply voice to: the prose of each angle's `angle` field and `rationale`, "
                "and the claim wording of each `key_finding`.\n\n"
                + load_prompt("team_voice_profile")
                + "\n=== END TEAM VOICE PROFILE ===\n"
            )

        prompt = (
            f"Topic: {topic}\n"
            f"Target tone: {tone}\n"
            f"{duration_prompt_block(duration_target, role='Analyst')}"
            f"Extract about {duration_target.analysis_findings_min}-"
            f"{duration_target.analysis_findings_max} key findings and aim for "
            f"{duration_target.selectable_angle_count} selectable angles. "
            f"Shorter episodes need fewer, stronger claims; longer episodes need "
            f"more context, protagonists, and visual evidence.\n"
            f"Total sources collected: {package.total_sources}\n"
            f"{gap_section}{focus_section}{inspiration_section}{voice_section}"
            f"\n=== RESEARCH SOURCES ===\n{_build_source_digest(package)}"
        )

        messages = [SystemMessage(content=load_prompt("analyst")), HumanMessage(content=prompt)]
        last_exc: Exception | None = None
        output: AnalysisOutput | None = None
        for attempt in range(3):
            try:
                result_raw = await self._structured_llm.ainvoke(messages)
                if result_raw and result_raw.key_findings:
                    output = result_raw
                    break
                log.warning("analyst.empty_response", attempt=attempt)
            except Exception as exc:
                last_exc = exc
                log.warning("analyst.retry", attempt=attempt, error=str(exc))

        if output is None:
            log.error("analyst.using_deterministic_fallback", topic=topic, error=str(last_exc))
            output = self._build_fallback_output(topic, package)

        source_id_by_ref: dict[str, str] = {}
        for i, src in enumerate(package.top_sources(12), 1):
            source_id_by_ref[f"source {i}"] = src.source_id
        for src in package.sources:
            for ref in (src.source_id, src.url, src.title):
                if ref:
                    source_id_by_ref[str(ref).strip().lower()] = src.source_id

        def _supporting_ids(kf: KeyFindingOutput) -> list[str]:
            ids = [sid for sid in kf.supporting_source_ids if sid in source_id_by_ref.values()]
            if ids:
                return ids
            resolved: list[str] = []
            for ref in [*kf.supporting_source_ids, *kf.supporting_sources]:
                ref_key = str(ref).strip().lower()
                source_id = source_id_by_ref.get(ref_key)
                if source_id and source_id not in resolved:
                    resolved.append(source_id)
            return resolved

        result = AnalysisResult(
            topic=topic,
            executive_summary=output.executive_summary,
            key_findings=[
                KeyFinding(
                    claim=kf.claim,
                    supporting_sources=kf.supporting_sources,
                    supporting_source_ids=_supporting_ids(kf),
                    confidence=kf.confidence,
                    category=kf.category,
                )
                for kf in output.key_findings
            ],
            narrative_angles=output.narrative_angles,
            data_gaps=output.data_gaps,
            recommended_tone=_normalize_tone(output.recommended_tone),
            controversies=output.controversies,
            notable_quotes=[
                {"quote": q.quote, "speaker": q.speaker, "source": q.source}
                for q in output.notable_quotes
            ],
            financial_metrics=output.financial_metrics,
        )
        generated_angles = [
            {
                "angle": angle.angle.strip(),
                "framing_axis": angle.framing_axis,
                "rationale": angle.rationale.strip(),
            }
            for angle in (output.selectable_angles or [])
        ]
        if len(generated_angles) < 3:
            generated_angles.extend(
                {
                    "angle": angle[:180],
                    "framing_axis": "explanatory",
                    "rationale": "Fallback from analyst narrative angle.",
                }
                for angle in output.narrative_angles
                if angle
            )
        if len(generated_angles) < 3:
            fallback_angles = [
                {
                    "angle": f"How {topic} became a story of money, risk, and timing",
                    "framing_axis": "explanatory",
                    "rationale": "Fallback angle built from the story topic.",
                },
                {
                    "angle": f"The human stakes behind {topic}",
                    "framing_axis": "human_interest",
                    "rationale": "Fallback angle that turns the topic toward people and consequences.",
                },
                {
                    "angle": f"What the numbers reveal about {topic}",
                    "framing_axis": "data_driven",
                    "rationale": "Fallback angle that centers sourced metrics and scale.",
                },
            ]
            existing = {angle["angle"] for angle in generated_angles}
            generated_angles.extend(
                angle for angle in fallback_angles if angle["angle"] not in existing
            )
        generated_angles = generated_angles[:5]
        for angle in generated_angles:
            words = angle["angle"].split()
            if len(words) > 24:
                angle["angle"] = " ".join(words[:24]).rstrip(",;:") + "..."

        log.info(
            "analyst.complete",
            topic=topic,
            findings=len(result.key_findings),
            narrative_angles=len(result.narrative_angles),
            selectable_angles=len(generated_angles),
        )

        return {
            "analysis_result": result,
            "generated_angles": generated_angles,
            "reference_packs": merge_reference_pack(state, reference_pack),
        }
