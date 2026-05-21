"""
Storyline Creator Agent — third node in the journalist pipeline.

Responsibilities:
  1. Receive structured AnalysisResult from the Analyst.
  2. Generate 2 distinct documentary storyline proposals.
  3. Select the strongest proposal as the primary candidate.
  4. Structure each storyline into timed acts that fit the requested episode length.
"""

import json
import re

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from backend.config import settings
from backend.models.research import AnalysisResult, StoryAct, StorylineProposal
from backend.services.duration_targets import (
    DurationTarget,
    act_timings_for_count,
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


# ── Structured output schemas ─────────────────────────────────────────────────

class StoryActOutput(BaseModel):
    act_number: int
    act_title: str
    purpose: str
    key_points: list[str]
    estimated_duration_seconds: int = 120
    required_visuals: list[str] = Field(default_factory=list)


class StorylineProposalOutput(BaseModel):
    title: str
    logline: str
    opening_hook: str
    unique_angle: str
    target_audience: str
    tone: str
    acts: list[StoryActOutput]
    closing_statement: str


class StorylineCreatorOutput(BaseModel):
    proposals: list[StorylineProposalOutput] = Field(default_factory=list)
    recommended_proposal_index: int = 0


# ── Editable prompt loaded from backend/prompts ──────────────────────────────



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
            max_tokens=4096,
            temperature=0.5,
        )
        self._structured_llm = self._llm.with_structured_output(StorylineCreatorOutput)

    @staticmethod
    def _squash_acts_to_limit(acts: list[StoryAct], max_count: int) -> list[StoryAct]:
        if len(acts) <= max_count:
            return acts

        grouped: list[StoryAct] = []
        total = len(acts)
        for index in range(max_count):
            start = round(index * total / max_count)
            end = round((index + 1) * total / max_count)
            chunk = acts[start:end] or [acts[min(start, total - 1)]]
            title = chunk[0].act_title
            if len(chunk) > 1:
                title = f"{chunk[0].act_title} / {chunk[-1].act_title}"

            purposes: list[str] = []
            key_points: list[str] = []
            visuals: list[str] = []
            for act in chunk:
                if act.purpose and act.purpose not in purposes:
                    purposes.append(act.purpose)
                for point in act.key_points:
                    if point not in key_points:
                        key_points.append(point)
                for visual in act.required_visuals:
                    if visual not in visuals:
                        visuals.append(visual)

            grouped.append(
                StoryAct(
                    act_number=index + 1,
                    act_title=title,
                    purpose="; ".join(purposes)[:320] or chunk[0].purpose,
                    key_points=key_points[:8],
                    estimated_duration_seconds=chunk[0].estimated_duration_seconds,
                    required_visuals=visuals[:6],
                )
            )

        return grouped

    @classmethod
    def _adapt_acts_to_duration(
        cls,
        acts: list[StoryAct],
        target: DurationTarget,
    ) -> list[StoryAct]:
        """Enforce act-count and timing differences across 5/10/15 minute scripts."""
        if not acts:
            return acts

        duration_acts = cls._squash_acts_to_limit(acts, target.act_count_max)
        timings = act_timings_for_count(target, len(duration_acts))
        return [
            StoryAct(
                act_number=index + 1,
                act_title=act.act_title,
                purpose=act.purpose,
                key_points=act.key_points,
                estimated_duration_seconds=timings[index],
                required_visuals=act.required_visuals,
            )
            for index, act in enumerate(duration_acts)
        ]

    @staticmethod
    def _extract_text_content(response: object) -> str:
        """Normalise Anthropic / LangChain responses into a plain string."""
        if isinstance(response, str):
            return response

        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif hasattr(block, "text"):
                    parts.append(getattr(block, "text"))
            return "\n".join(part for part in parts if part).strip()

        return str(content)

    @staticmethod
    def _extract_json_payload(text: str) -> dict:
        """Extract the first JSON object from a model response."""
        stripped = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
        if fenced:
            stripped = fenced.group(1)
        elif not stripped.startswith("{"):
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError("No JSON object found in fallback response.")
            stripped = stripped[start:end + 1]

        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Fallback JSON parse failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Fallback response JSON must be an object.")
        return payload

    def _build_fallback_output(
        self,
        topic: str,
        tone: str,
        analysis: AnalysisResult,
    ) -> StorylineCreatorOutput:
        """Create a conservative storyline when the model does not return valid structure."""
        findings = [f.claim for f in analysis.key_findings[:6]] or [analysis.executive_summary]
        angles = analysis.narrative_angles[:3] or [analysis.executive_summary]
        quotes = [
            f"{q.get('speaker', 'Source')}: {q.get('quote', '')}".strip(": ")
            for q in analysis.notable_quotes[:2]
            if q.get("quote")
        ]
        controversies = analysis.controversies[:2]

        acts = [
            StoryActOutput(
                act_number=1,
                act_title="Why This Story Matters",
                purpose="Hook & stakes",
                key_points=[findings[0], angles[0]],
                estimated_duration_seconds=110,
                required_visuals=["Opening montage tied to the central claim"],
            ),
            StoryActOutput(
                act_number=2,
                act_title="How We Got Here",
                purpose="Context & history",
                key_points=[analysis.executive_summary, *findings[1:3]],
                estimated_duration_seconds=140,
                required_visuals=["Historical timeline graphics", "Contextual archive footage"],
            ),
            StoryActOutput(
                act_number=3,
                act_title="The Core Evidence",
                purpose="Evidence & exploration",
                key_points=[*findings[3:5], *(controversies or angles[1:2])],
                estimated_duration_seconds=170,
                required_visuals=["Charts, reporting clips, and primary evidence visuals"],
            ),
            StoryActOutput(
                act_number=4,
                act_title="The Human Angle",
                purpose="Human element",
                key_points=quotes or [angles[-1], *(analysis.data_gaps[:1] or ["Who is most affected and why?"])],
                estimated_duration_seconds=150,
                required_visuals=["Interview setups and on-the-ground footage"],
            ),
            StoryActOutput(
                act_number=5,
                act_title="What Comes Next",
                purpose="Resolution & forward look",
                key_points=analysis.data_gaps[:2] or ["What this means next for the audience"],
                estimated_duration_seconds=90,
                required_visuals=["Forward-looking visuals and closing montage"],
            ),
        ]

        primary = StorylineProposalOutput(
            title=topic[:90],
            logline=analysis.executive_summary[:220],
            opening_hook=findings[0],
            unique_angle=angles[0],
            target_audience="Business, policy, and documentary viewers",
            tone=tone,
            acts=acts,
            closing_statement=analysis.data_gaps[0] if analysis.data_gaps else "The next chapter of this story is already taking shape.",
        )

        alternate = StorylineProposalOutput(
            title=f"Inside {topic[:72]}",
            logline=(angles[0] if angles else analysis.executive_summary)[:220],
            opening_hook=quotes[0] if quotes else findings[0],
            unique_angle=angles[1] if len(angles) > 1 else "A tighter focus on the people and decisions behind the story",
            target_audience="General business and current-affairs audience",
            tone=tone,
            acts=acts,
            closing_statement=primary.closing_statement,
        )

        return StorylineCreatorOutput(
            proposals=[primary, alternate],
            recommended_proposal_index=0,
        )

    async def _invoke_fallback_json(self, messages: list[object]) -> StorylineCreatorOutput:
        """
        Ask the base model for strict JSON when structured parsing fails.
        This catches cases where the model returns `{}` or malformed tool output.
        """
        schema_hint = (
            "Return ONLY valid JSON. No markdown fences. "
            "Use this exact top-level shape: "
            '{"proposals":[{"title":"","logline":"","opening_hook":"","unique_angle":"",'
            '"target_audience":"","tone":"","acts":[{"act_number":1,"act_title":"",'
            '"purpose":"","key_points":[""],"estimated_duration_seconds":120,'
            '"required_visuals":[""]}],"closing_statement":""}],"recommended_proposal_index":0}'
        )
        response = await self._llm.ainvoke([
            *messages,
            HumanMessage(content=schema_hint),
        ])
        payload = self._extract_json_payload(self._extract_text_content(response))
        return StorylineCreatorOutput.model_validate(payload)

    async def run(self, state: dict) -> dict:
        analysis: AnalysisResult | None = state.get("analysis_result")
        if analysis is None:
            raise ValueError("storyline_creator received no analysis_result")
        topic: str = state["topic"]
        tone: str = state.get("tone") or analysis.recommended_tone
        duration_target = duration_target_for(state.get("target_duration_minutes"))
        target_duration_minutes = duration_target.minutes
        target_audience: str | None = state.get("target_audience")
        refinement_cycle: int = state.get("refinement_cycle", 0)
        rewrite_recommendations: list[str] = state.get("user_rewrite_recommendations") or []
        selected_angle: str | None = state.get("selected_angle")

        evaluation_feedback = ""
        if refinement_cycle > 0 and state.get("evaluation_report"):
            ev = state["evaluation_report"]
            recommendations = (
                ev.scriptwriter_recommendations
                or ev.improvement_suggestions
                or ev.weaknesses
            )
            evaluation_feedback = (
                f"\n\nPREVIOUS EVALUATION FEEDBACK (cycle {refinement_cycle}):\n"
                f"Weaknesses: {chr(10).join(ev.weaknesses)}\n"
                f"Recommendations: {chr(10).join(recommendations)}\n"
                f"Address these recommendations in the new proposals."
            )

        recommendation_feedback = ""
        if rewrite_recommendations:
            recommendation_feedback = (
                "\n\nTARGETED REVISION GOALS:\n"
                + "\n".join(f"- {item}" for item in rewrite_recommendations)
                + "\nAddress these goals directly in the title, opening hook, act structure, evidence choices, "
                  "human element placement, and closing statement wherever relevant."
            )

        log.info("storyline_creator.start", topic=topic, refinement_cycle=refinement_cycle)

        angle_directive = ""
        if selected_angle:
            angle_directive = (
                f"\n=== PRIMARY CREATIVE DIRECTIVE (user-selected angle) ===\n"
                f"{selected_angle}\n"
                "Both proposals must execute on this angle. Title, logline, opening hook, "
                "act structure, and closing statement should all serve this framing.\n"
            )

        reference_pack = get_reference_pack(
            role="storyline_creator",
            topic=topic,
            state=state,
            max_cards=5,
            token_budget=1500,
        )
        reference_section = ""
        reference_context = format_reference_pack(reference_pack)
        if reference_context:
            reference_section = (
                f"\n{reference_context}\n"
                "Use the pack to shape act architecture, escalation, human-story placement, "
                "and closing payoff. Do not copy example wording.\n"
            )

        voice_section = ""
        if settings.enable_team_voice_profile:
            voice_section = (
                "\n=== TEAM VOICE PROFILE (wording polish only) ===\n"
                "You are about to generate a StorylineProposal: a documentary title, "
                "logline, and act_titles.\n\n"
                "Your writing decisions follow a clear hierarchy:\n"
                "1. PRIMARY — The library corpus (above) and the EPISODE DURATION "
                "CONTRACT are the source of truth for craft and structure. The reference "
                "pack cards show you the structural patterns successful documentaries use: "
                "how hooks work, how acts are titled, what a strong logline does, how the "
                "corpus distributes attention across acts. Base every structural decision "
                "on these patterns and on the duration contract's act count and per-act "
                "seconds.\n\n"
                "2. SECONDARY — Voice is the final polish on top of (1). Once you have "
                "decided WHAT the title, logline, and act_titles should communicate "
                "(informed by the library), use the TEAM VOICE PROFILE below ONLY to "
                "refine HOW those strings are worded. Voice never changes the structural "
                "decision; it only sharpens the wording.\n\n"
                "Apply voice to: the prose of `title`, `logline`, and each `act_title` "
                "string. Do not let voice rules push you to change act count, act "
                "ordering, duration distribution, or which subject each act covers — "
                "those are library-and-duration decisions, already settled before voice "
                "runs.\n\n"
                + load_prompt("team_voice_profile")
                + "\n=== END TEAM VOICE PROFILE ===\n"
            )
        timing_plan = act_timings_for_count(duration_target)
        duration_contract = (
            f"{duration_prompt_block(duration_target, role='Storyline Creator')}"
            "Mandatory structure: each proposal must fit this duration contract. "
            f"Use {duration_target.recommended_act_count} acts when possible, and never "
            f"exceed {duration_target.act_count_max} acts for this target.\n"
            "Recommended act timing plan: "
            + ", ".join(
                f"Act {index + 1}: {seconds}s"
                for index, seconds in enumerate(timing_plan)
            )
            + "\n"
        )

        prompt = (
            f"Topic: {topic}\n"
            f"Target tone: {tone}\n"
            f"Target duration: {target_duration_minutes} minutes\n"
            f"Target audience: {target_audience or 'General documentary audience'}\n"
            f"{duration_contract}"
            f"{angle_directive}{reference_section}{voice_section}\n"
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
            + recommendation_feedback
        )

        messages = [SystemMessage(content=load_prompt("storyline_creator")), HumanMessage(content=prompt)]
        last_exc: Exception | None = None
        output: StorylineCreatorOutput | None = None
        for attempt in range(3):
            try:
                result = await self._structured_llm.ainvoke(messages)
                if result and result.proposals:
                    output = result
                    break
                log.warning("storyline_creator.empty_response", attempt=attempt)
            except (ValidationError, ValueError, TypeError) as exc:
                last_exc = exc
                log.warning("storyline_creator.retry", attempt=attempt, error=str(exc))
                try:
                    recovered = await self._invoke_fallback_json(messages)
                    if recovered.proposals:
                        output = recovered
                        log.info("storyline_creator.recovered_with_json_fallback", attempt=attempt)
                        break
                except Exception as fallback_exc:
                    last_exc = fallback_exc
                    log.warning(
                        "storyline_creator.json_fallback_failed",
                        attempt=attempt,
                        error=str(fallback_exc),
                    )
            except Exception as exc:
                last_exc = exc
                log.warning("storyline_creator.retry", attempt=attempt, error=str(exc))

        if output is None:
            log.error(
                "storyline_creator.using_deterministic_fallback",
                topic=topic,
                error=str(last_exc) if last_exc else "empty response",
            )
            output = self._build_fallback_output(topic=topic, tone=tone, analysis=analysis)

        proposals: list[StorylineProposal] = []
        for p in output.proposals:
            acts = [
                StoryAct(
                    act_number=a.act_number,
                    act_title=a.act_title,
                    purpose=a.purpose,
                    key_points=a.key_points,
                    estimated_duration_seconds=a.estimated_duration_seconds,
                    required_visuals=a.required_visuals,
                )
                for a in p.acts
            ]
            acts = self._adapt_acts_to_duration(acts, duration_target)
            proposal = StorylineProposal(
                title=p.title,
                logline=p.logline,
                opening_hook=p.opening_hook,
                acts=acts,
                closing_statement=p.closing_statement,
                unique_angle=p.unique_angle,
                target_audience=p.target_audience,
                tone=p.tone,
            )
            proposal.compute_duration()
            proposals.append(proposal)

        if not proposals:
            raise ValueError("StorylineCreator produced no proposals.")

        recommended_idx = min(output.recommended_proposal_index, len(proposals) - 1)
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
            "reference_packs": merge_reference_pack(state, reference_pack),
        }
