"""
Scriptwriter Agent — final node in the journalist pipeline.

Responsibilities:
  1. Receive the approved storyline and full research package.
  2. Write a complete, production-ready narrator script act-by-act in parallel.
  3. Include on-screen text, b-roll cues, and interview prompts.
  4. Upload the finished script to S3.
  5. Persist word count, duration estimate, and S3 key back into state.
"""

import asyncio
import uuid

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import AnalysisResult, StorylineProposal
from backend.models.story import FinalScript, ScriptSection
from backend.services.duration_targets import (
    WORDS_PER_MINUTE,
    duration_prompt_block,
    duration_target_for,
)
from backend.services.library_knowledge import (
    format_reference_pack,
    get_reference_pack,
    merge_reference_pack,
)
from backend.services.prompt_loader import load_prompt
from backend.services.script_storage import upload_script_to_s3

log = structlog.get_logger(__name__)

_WORDS_PER_MINUTE = WORDS_PER_MINUTE


# ── Structured output schema ──────────────────────────────────────────────────

class ActOutput(BaseModel):
    narration: str = Field(description="Full narrator script for this act — complete sentences, natural cadence")
    word_count: int = Field(description="Word count of the narration")
    source_ids: list[str] = Field(default_factory=list, description="Source IDs used for the factual claims in this act")


# ── Editable prompt loaded from backend/prompts ──────────────────────────────



class ScriptwriterAgent:
    """
    Production-ready scriptwriter that generates act-by-act documentary narration.

    Example::

        agent = ScriptwriterAgent()
        state_updates = await agent.run(state)
    """

    def __init__(self) -> None:
        _llm = ChatAnthropic(
            model=settings.claude_opus_model,
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
        )
        self._structured_llm = _llm.with_structured_output(ActOutput)

    async def _write_act(
        self,
        act_data: dict,
        storyline: StorylineProposal,
        analysis: AnalysisResult,
        source_lookup: dict[str, dict],
        topic: str,
        target_audience: str | None = None,
        rewrite_recommendations: list[str] | None = None,
        act_arc: str = "",
        previous_act: dict | None = None,
        next_act: dict | None = None,
        selected_angle: str | None = None,
        library_reference: str = "",
        duration_contract: str = "",
    ) -> ScriptSection:
        """Write narration for a single act."""
        relevant_quotes = "\n".join(
            f'  "{q["quote"]}" — {q["speaker"]}'
            for q in analysis.notable_quotes[:3]
        )
        relevant_findings = "\n".join(
            (
                f"  - {f.claim}"
                f" [source_ids: {', '.join(f.supporting_source_ids) or 'unlinked'}]"
                f" [confidence: {f.confidence:.2f}; category: {f.category}]"
            )
            for f in analysis.key_findings[:14]
        )[:4000]
        source_brief = "\n".join(
            (
                f"  - {source_id}: {source.get('title', 'Untitled')}"
                f" ({source.get('credibility', 'medium')}, {source.get('type', 'source')})\n"
                f"    Excerpt: {source.get('excerpt') or 'No excerpt available.'}"
            )
            for source_id, source in list(source_lookup.items())[:12]
        )
        revision_goals = ""
        if rewrite_recommendations:
            revision_goals = (
                "=== EVALUATOR AGENT RECOMMENDATIONS TO APPLY WHILE WRITING ===\n"
                "These recommendations were passed from the Evaluator Agent. Treat them as "
                "mandatory editorial direction for this act unless they conflict with verified source facts.\n"
                + "\n".join(f"  - {item}" for item in rewrite_recommendations)
                + "\n\n"
            )
        previous_context = (
            f"Previous act: Act {previous_act['act_number']} - {previous_act['act_title']}\n"
            f"Previous act purpose: {previous_act['purpose']}\n"
            if previous_act else "Previous act: None. This is the opening act.\n"
        )
        next_context = (
            f"Next act: Act {next_act['act_number']} - {next_act['act_title']}\n"
            f"Next act purpose: {next_act['purpose']}\n"
            if next_act else "Next act: None. This is the closing act.\n"
        )

        angle_directive = ""
        if selected_angle:
            angle_directive = (
                "=== PRIMARY CREATIVE DIRECTIVE (user-selected angle) ===\n"
                f"{selected_angle}\n"
                "This is the frame the script must execute on. Every sentence of narration "
                "in this act should advance or reinforce this angle.\n\n"
            )

        prompt = (
            f"Documentary: {storyline.title}\n"
            f"Logline: {storyline.logline}\n"
            f"Overall tone: {storyline.tone}\n\n"
            f"Target audience: {target_audience or storyline.target_audience}\n\n"
            f"{duration_contract}"
            f"{angle_directive}"
            f"{revision_goals}"
            f"=== FULL STORY ARC ===\n{act_arc}\n\n"
            f"=== CONTINUITY CONTEXT ===\n{previous_context}{next_context}\n"
            f"{library_reference}"
            f"=== ACT TO WRITE ===\n"
            f"Act {act_data['act_number']}: {act_data['act_title']}\n"
            f"Purpose: {act_data['purpose']}\n"
            f"Key points to cover:\n"
            + "\n".join(f"  - {kp}" for kp in act_data.get("key_points", []))
            + f"\nTarget duration: {act_data['estimated_duration_seconds']} seconds\n"
            f"Target word count: {int(act_data['estimated_duration_seconds'] / 60 * _WORDS_PER_MINUTE)}\n\n"
            f"=== RELEVANT RESEARCH ===\n"
            f"Key facts:\n{relevant_findings or '  No verified findings were extracted; keep factual claims minimal.'}\n\n"
            f"Source lookup:\n{source_brief or '  No source lookup available.'}\n\n"
            f"Notable quotes:\n{relevant_quotes or '  (none available)'}\n\n"
            "Return source_ids containing only IDs from the source lookup that support this act. "
            "If a factual claim is not supported by a listed source ID, do not include that claim."
        )

        output: ActOutput = await self._structured_llm.ainvoke([
            SystemMessage(content=load_prompt("scriptwriter")),
            HumanMessage(content=prompt),
        ])

        return ScriptSection(
            section_number=act_data["act_number"],
            title=act_data["act_title"],
            narration=output.narration,
            estimated_seconds=act_data["estimated_duration_seconds"],
            source_ids=[sid for sid in output.source_ids if sid in source_lookup],
        )

    async def run(self, state: dict) -> dict:
        storyline: StorylineProposal = state["selected_storyline"]
        analysis: AnalysisResult = state["analysis_result"]
        topic: str = state["topic"]
        story_id: str = state["story_id"]
        duration_target = duration_target_for(state.get("target_duration_minutes"))
        target_duration_minutes = duration_target.minutes
        target_audience = state.get("target_audience")
        rewrite_recommendations: list[str] = state.get("user_rewrite_recommendations") or []
        evaluator_recommendations: list[str] = state.get("scriptwriter_recommendations") or []
        if evaluator_recommendations:
            rewrite_recommendations = evaluator_recommendations + rewrite_recommendations
        duration_scale = duration_target.seconds / max(
            storyline.total_estimated_duration_seconds,
            1,
        )

        log.info("scriptwriter.start", topic=topic, acts=len(storyline.acts))
        source_lookup = {
            src.source_id: {
                "title": src.title,
                "url": src.url,
                "credibility": src.credibility.value,
                "type": src.source_type.value,
                "excerpt": src.content[:500],
            }
            for src in state["research_package"].top_sources(20)
        }
        act_plans = [
            {
                "act_number": act.act_number,
                "act_title": act.act_title,
                "purpose": act.purpose,
                "key_points": act.key_points,
                "estimated_duration_seconds": max(60, round(act.estimated_duration_seconds * duration_scale)),
            }
            for act in storyline.acts
        ]
        duration_contract = (
            f"{duration_prompt_block(duration_target, role='Scriptwriter')}"
            f"Target total word count for the complete script: {duration_target.target_word_count}.\n"
            "Each act must stay close to its target word count; do not write a generic "
            "10-minute act when this is a 5-minute or 15-minute request.\n\n"
        )
        act_arc = "\n".join(
            (
                f"Act {act['act_number']}: {act['act_title']} "
                f"({act['estimated_duration_seconds']}s)\n"
                f"Purpose: {act['purpose']}\n"
                f"Key points: {', '.join(act.get('key_points', [])) or 'None'}"
            )
            for act in act_plans
        )

        selected_angle: str | None = state.get("selected_angle")
        reference_pack = get_reference_pack(
            role="scriptwriter",
            topic=topic,
            state=state,
            max_cards=6,
            token_budget=1800,
        )
        reference_context = format_reference_pack(reference_pack)
        library_reference = ""
        if reference_context:
            library_reference = (
                f"=== SCRIPTWRITER LIBRARY REFERENCE ===\n{reference_context}\n"
                "Use this only for narration shape, specificity, transitions, and cadence. "
                "Facts must come from the research package below.\n\n"
            )

        # Write acts in parallel while giving each one the full arc for continuity.
        act_tasks = [
            self._write_act(
                act_data=act_data,
                storyline=storyline,
                analysis=analysis,
                source_lookup=source_lookup,
                topic=topic,
                target_audience=target_audience,
                rewrite_recommendations=rewrite_recommendations,
                act_arc=act_arc,
                previous_act=act_plans[index - 1] if index > 0 else None,
                next_act=act_plans[index + 1] if index + 1 < len(act_plans) else None,
                selected_angle=selected_angle,
                library_reference=library_reference,
                duration_contract=duration_contract,
            )
            for index, act_data in enumerate(act_plans)
        ]
        sections: list[ScriptSection] = list(await asyncio.gather(*act_tasks))

        total_words = sum(len(s.narration.split()) for s in sections)
        duration_minutes = total_words / _WORDS_PER_MINUTE

        source_refs = [
            {
                "source_id": src.source_id,
                "title": src.title,
                "url": src.url,
                "credibility": src.credibility.value,
                "type": src.source_type.value,
            }
            for src in state["research_package"].top_sources(20)
        ]

        final_script = FinalScript(
            story_id=uuid.UUID(story_id),
            title=storyline.title,
            logline=storyline.logline,
            opening_hook=storyline.opening_hook,
            sections=sections,
            closing_statement=storyline.closing_statement,
            total_word_count=total_words,
            estimated_duration_minutes=round(duration_minutes, 1),
            sources=source_refs,
            metadata={
                "topic": topic,
                "tone": storyline.tone,
                "target_duration_minutes": target_duration_minutes,
                "target_duration_seconds": duration_target.seconds,
                "target_word_count": duration_target.target_word_count,
                "duration_profile": duration_target.label,
                "target_act_count": duration_target.recommended_act_count,
                "target_audience": target_audience or storyline.target_audience,
                "unique_angle": storyline.unique_angle,
                "scriptwriter_recommendations": rewrite_recommendations[:10],
                "library_reference_cards": len(reference_pack.cards),
            },
        )

        s3_key: str | None = None
        try:
            s3_key = await upload_script_to_s3(final_script)
        except Exception as exc:
            log.warning("scriptwriter.s3_upload_failed", error=str(exc))

        log.info(
            "scriptwriter.complete",
            title=storyline.title,
            word_count=total_words,
            duration_min=f"{duration_minutes:.1f}",
        )

        return {
            "final_script": final_script,
            "script_s3_key": s3_key,
            "reference_packs": merge_reference_pack(state, reference_pack),
        }
