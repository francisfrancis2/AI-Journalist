"""
Angles & Hooks Agent.

This is the canonical ideation/angle/hook agent in the five-agent model. It
also owns the research-analysis skill used by the script pipeline, delegating to
the embedded angle-synthesis skill so current tested behavior remains
stable.
"""

from typing import Any, Optional

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.agents._angle_synthesis_skill import AngleSynthesisSkill
from backend.config import settings
from backend.models.story import IdeationStage, StoryORM
from backend.services.library_knowledge import format_reference_pack, get_reference_pack
from backend.services.prompt_loader import load_prompt

log = structlog.get_logger(__name__)


class IdeationAngleOutput(BaseModel):
    angle: str
    framing_axis: str = "explanatory"
    rationale: str = ""


class IdeationChapterOutput(BaseModel):
    chapter_number: int
    title: str
    purpose: str
    key_points: list[str] = Field(default_factory=list)


class IdeationOutput(BaseModel):
    assistant_message: str
    title: Optional[str] = None
    decided_tone: str = "explanatory"
    target_duration_minutes: int = 10
    angles: list[IdeationAngleOutput] = Field(default_factory=list)
    hook_options: list[str] = Field(default_factory=list)
    story_hook: Optional[str] = None
    chapters: list[IdeationChapterOutput] = Field(default_factory=list)


def normalise_story_tone(value: str) -> str:
    tone = (value or "").strip().lower()
    remap = {"trend": "investigative", "profile": "narrative"}
    tone = remap.get(tone, tone)
    return tone if tone in {"investigative", "explanatory", "narrative"} else "explanatory"


def normalise_target_duration(value: int | str | None) -> int:
    try:
        minutes = int(value or 10)
    except (TypeError, ValueError):
        minutes = 10
    if minutes <= 7:
        return 5
    if minutes >= 13:
        return 15
    return 10


def compact_ideation_context(story: StoryORM) -> str:
    angles = story.angles_data or []
    chapters = story.chapters_data or []
    hook_options = story.hook_options_data or []
    return "\n".join(
        [
            f"Topic: {story.topic}",
            f"Current title: {story.title}",
            f"Backend-decided tone: {story.tone}",
            f"Backend-decided duration: {story.target_duration_minutes} minutes",
            f"Ideation stage: {story.ideation_stage or IdeationStage.PROMPT.value}",
            f"Selected angle: {story.selected_angle or 'None yet'}",
            "Current angles:",
            str(angles)[:2500] if angles else "[]",
            f"Story hook: {story.story_hook or 'None yet'}",
            "Current hook options:",
            str(hook_options)[:2500] if hook_options else "[]",
            "Current chapters:",
            str(chapters)[:2500] if chapters else "[]",
        ]
    )


def fallback_ideation_output(
    *,
    topic: str,
    stage: IdeationStage,
    selected_angle: Optional[str] = None,
    hook: Optional[str] = None,
) -> IdeationOutput:
    angle_base = topic.rstrip(".")
    angles = [
        IdeationAngleOutput(
            angle=f"How {angle_base} became a story of money, risk, and timing",
            framing_axis="explanatory",
            rationale="Frames the topic as a clear cause-and-effect documentary.",
        ),
        IdeationAngleOutput(
            angle=f"The human stakes behind {angle_base}",
            framing_axis="human_interest",
            rationale="Pulls the story toward people affected by the change.",
        ),
        IdeationAngleOutput(
            angle=f"What the numbers reveal about {angle_base}",
            framing_axis="data_driven",
            rationale="Centers verifiable scale, costs, and measurable consequences.",
        ),
    ]
    story_hook = hook or (
        f"This episode follows {angle_base} through the decisions, incentives, and consequences "
        "that turn a familiar headline into a sharper documentary story."
    )
    hook_options = [
        story_hook,
        f"What if {selected_angle or angle_base} is not a side story, but the clue that explains who wins next?",
        f"The story begins with one visible shift in {angle_base}, then follows the hidden choices that made it inevitable.",
    ]
    return IdeationOutput(
        assistant_message="I drafted a practical editorial starting point. We can push it in a sharper direction from here.",
        title=f"Story: {topic[:80]}",
        decided_tone="explanatory",
        target_duration_minutes=10,
        angles=angles if stage == IdeationStage.ANGLES else [],
        hook_options=hook_options if stage == IdeationStage.HOOK else [],
        story_hook=story_hook if stage == IdeationStage.HOOK else None,
    )


class AnglesAndHooksAgent:
    """
    Owns early story ideation, angle refinement, hook writing, and the pipeline
    analysis skill that turns research into selectable editorial direction.
    """

    def __init__(self) -> None:
        self._analysis_skill = AngleSynthesisSkill()
        _llm = ChatAnthropic(
            model=settings.claude_haiku_model,
            api_key=settings.anthropic_api_key,
            max_tokens=2500,
            temperature=0.35,
        )
        self._structured_llm = _llm.with_structured_output(IdeationOutput)

    async def analyze_research(self, state: dict[str, Any]) -> dict[str, Any]:
        """Pipeline skill: turn full research into editorial analysis and angles."""
        return await self._analysis_skill.run(state)

    async def run(
        self,
        *,
        story: StoryORM,
        user_message: str,
        stage: IdeationStage,
        fresh_research_context: str = "",
    ) -> IdeationOutput:
        """Generate or refine angles/hooks for the current ideation stage."""
        if stage == IdeationStage.CHAPTERS:
            raise ValueError("Chapter planning belongs to ChapterWriterAgent.")

        stage_rules = {
            IdeationStage.ANGLES: (
                "Active stage: angles. Return 3-5 producer-selectable angles. "
                "They must differ by framing, not just wording. Each angle should be one sentence."
            ),
            IdeationStage.HOOK: (
                "Active stage: story hook. Return exactly 3 distinct pitch-style hook_options under 100 words each, "
                "based on the selected angle. Also set story_hook to the strongest option. Each hook should describe "
                "the main idea and tension, not the full script."
            ),
            IdeationStage.PROMPT: "Active stage: prompt. Help clarify the rough story idea.",
            IdeationStage.READY_FOR_SCRIPT: "Active stage: ready for script. Help verify the plan before scripting.",
        }[stage]
        reference_pack = get_reference_pack(
            role="angles_and_hooks",
            topic=story.topic,
            state={
                "selected_angle": story.selected_angle,
                "story_hook": story.story_hook,
                "generated_angles": story.angles_data or [],
            },
            max_cards=5,
            token_budget=1400,
        )
        reference_context = format_reference_pack(reference_pack)
        prompt = (
            f"{stage_rules}\n\n"
            f"=== CURRENT STORY CONTEXT ===\n{compact_ideation_context(story)}\n\n"
            f"=== RECENT CHAT ===\n"
            + "\n".join(
                f"{item.get('role', 'user')}: {str(item.get('content', ''))[:600]}"
                for item in (story.ideation_chat_data or [])[-10:]
                if isinstance(item, dict)
            )
            + f"\n\n=== FRESH RESEARCH CONTEXT ===\n{fresh_research_context or 'No fresh research was fetched for this turn.'}\n\n"
            f"{reference_context}\n\n"
            f"User request: {user_message}\n\n"
            "Also decide the most fitting documentary tone: investigative, explanatory, or narrative. "
            "Decide target duration as 5, 10, or 15 minutes based on complexity."
        )

        try:
            output: IdeationOutput = await self._structured_llm.ainvoke(
                [SystemMessage(content=load_prompt("angles_and_hooks")), HumanMessage(content=prompt)]
            )
        except Exception as exc:
            log.warning("angles_and_hooks.fallback", story_id=str(story.id), stage=stage, error=str(exc))
            output = fallback_ideation_output(
                topic=story.topic,
                stage=stage,
                selected_angle=story.selected_angle,
                hook=story.story_hook,
            )

        output.decided_tone = normalise_story_tone(output.decided_tone)
        output.target_duration_minutes = normalise_target_duration(output.target_duration_minutes)
        if stage == IdeationStage.HOOK and output.story_hook:
            words = output.story_hook.split()
            if len(words) > 100:
                output.story_hook = " ".join(words[:100]).rstrip(",;:")
        if stage == IdeationStage.HOOK:
            cleaned_hooks: list[str] = []
            for hook_option in output.hook_options:
                hook_text = " ".join((hook_option or "").strip().split())
                if not hook_text:
                    continue
                words = hook_text.split()
                if len(words) > 100:
                    hook_text = " ".join(words[:100]).rstrip(",;:")
                if hook_text not in cleaned_hooks:
                    cleaned_hooks.append(hook_text)
            if output.story_hook:
                story_hook = " ".join(output.story_hook.strip().split())
                if story_hook and story_hook not in cleaned_hooks:
                    cleaned_hooks.insert(0, story_hook)
            output.hook_options = cleaned_hooks[:6]
            if not output.story_hook and output.hook_options:
                output.story_hook = output.hook_options[0]
        return output
