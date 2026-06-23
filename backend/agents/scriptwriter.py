"""
Scriptwriter Agent — final node in the journalist pipeline.

Responsibilities:
  1. Receive the approved storyline and full research package.
  2. Write a complete, production-ready narrator script act-by-act in parallel.
  3. Include on-screen text, b-roll cues, and interview prompts.
  4. Persist word count and duration estimate back into state.
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

    @staticmethod
    def _decide_treatment(
        *,
        state: dict,
        storyline: StorylineProposal,
        analysis: AnalysisResult,
    ) -> dict[str, str]:
        """
        Backend treatment-selection skill embedded in Scriptwriter.

        Ideation can suggest tone, but final script generation decides the
        executable story treatment from all approved inputs.
        """
        context = " ".join(
            str(item or "")
            for item in [
                state.get("selected_angle"),
                state.get("story_hook"),
                storyline.unique_angle,
                storyline.logline,
                analysis.executive_summary,
            ]
        ).lower()
        narrative_terms = {
            "person",
            "people",
            "worker",
            "founder",
            "family",
            "journey",
            "life",
            "human",
            "character",
            "protagonist",
        }
        investigative_terms = {
            "hidden",
            "behind",
            "risk",
            "crisis",
            "controversy",
            "scandal",
            "power",
            "money",
            "influence",
            "accountability",
            "exposed",
        }
        if any(term in context for term in narrative_terms):
            tone = "narrative"
        elif any(term in context for term in investigative_terms):
            tone = "investigative"
        else:
            tone = (
                str(state.get("tone") or analysis.recommended_tone or storyline.tone or "explanatory")
                .strip()
                .lower()
            )
        if tone not in {"investigative", "explanatory", "narrative"}:
            tone = "explanatory"

        return {
            "story_type": tone,
            "tone": tone,
            "notes": (
                "Final backend treatment selected by Scriptwriter from approved angle, "
                "hook, chapter plan, storyline, and editorial analysis."
            ),
        }

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
        voice_section: str = "",
        duration_contract: str = "",
        treatment_directive: str = "",
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
                "=== CHIEF EDITOR RECOMMENDATIONS TO APPLY WHILE WRITING ===\n"
                "These recommendations were passed from the Chief Editor. Treat them as "
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
            f"{treatment_directive}"
            f"{angle_directive}"
            f"{revision_goals}"
            f"=== FULL STORY ARC ===\n{act_arc}\n\n"
            f"=== CONTINUITY CONTEXT ===\n{previous_context}{next_context}\n"
            f"{library_reference}"
            f"{voice_section}"
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
        treatment = self._decide_treatment(
            state=state,
            storyline=storyline,
            analysis=analysis,
        )
        if storyline.tone != treatment["tone"]:
            storyline = storyline.model_copy(update={"tone": treatment["tone"]})
        duration_scale = duration_target.seconds / max(
            storyline.total_estimated_duration_seconds,
            1,
        )

        log.info(
            "scriptwriter.start",
            topic=topic,
            acts=len(storyline.acts),
            treatment=treatment["story_type"],
        )
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
        treatment_directive = (
            "=== SCRIPTWRITER TREATMENT DECISION ===\n"
            f"Story type: {treatment['story_type']}\n"
            f"Tone: {treatment['tone']}\n"
            f"Notes: {treatment['notes']}\n"
            "This backend decision supersedes earlier UI/default tone suggestions for final drafting.\n\n"
        )
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

        voice_section = ""
        if settings.enable_team_voice_profile:
            voice_section = (
                "=== TEAM VOICE PROFILE (wording polish only) ===\n"
                "You are writing the NARRATION for one act of the final script.\n\n"
                "Your writing decisions follow a clear hierarchy:\n"
                "1. PRIMARY — The library corpus reference pack (above), the research "
                "sources, the act plan, and the EPISODE DURATION CONTRACT are the source "
                "of truth for craft, content, and length. The reference pack teaches you "
                "how this genre of documentary writes acts at this duration: opening "
                "moves, evidence placement, transition style, closing devices. Base your "
                "craft decisions on these corpus-derived patterns. Base your factual "
                "claims strictly on the research sources and key findings provided. Hit "
                "the word-count target in the duration contract.\n\n"
                "2. SECONDARY — Voice is the final polish on top of (1). Once you have "
                "written narration that follows the corpus's craft patterns and stays "
                "within the research and word budget, use the TEAM VOICE PROFILE below "
                "to refine HOW each sentence sounds: sentence cadence, signature pivots, "
                "rhetorical devices, concreteness, cultural anchoring, punctuation, and "
                "the close pattern (for the final act). Voice never changes WHAT facts "
                "you assert, which sources you cite, what the act covers, or how long "
                "it is.\n\n"
                "Hard rules from voice (anti-patterns): no item from the anti-patterns "
                "list ever appears in the narration, even if voice has otherwise "
                "finished its job. Treat it as a final check before you commit output.\n\n"
                "Conflict resolution:\n"
                "- If a voice device would require inventing a fact, drop the device.\n"
                "- If a voice device would push the act over its word budget, drop it.\n"
                "- If a corpus pattern conflicts with a voice device, corpus wins.\n\n"
                + load_prompt("team_voice_profile")
                + "\n=== END TEAM VOICE PROFILE ===\n\n"
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
                voice_section=voice_section,
                duration_contract=duration_contract,
                treatment_directive=treatment_directive,
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
                "story_type": treatment["story_type"],
                "tone": treatment["tone"],
                "treatment_notes": treatment["notes"],
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

        log.info(
            "scriptwriter.complete",
            title=storyline.title,
            word_count=total_words,
            duration_min=f"{duration_minutes:.1f}",
        )

        return {
            "final_script": final_script,
            "reference_packs": merge_reference_pack(state, reference_pack),
        }
