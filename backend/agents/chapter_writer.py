"""Chapter Writer Agent for planning chapters and production story structure."""

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.angles_and_hooks import (
    IdeationChapterOutput,
    IdeationOutput,
    compact_ideation_context,
    normalise_story_tone,
    normalise_target_duration,
)
from backend.agents._chapter_structure_skill import (
    ChapterStructureSkill,
    StoryActOutput,
    StorylineCreatorOutput,
    StorylineProposalOutput,
)
from backend.config import settings
from backend.models.story import StoryORM
from backend.services.library_knowledge import format_reference_pack, get_reference_pack
from backend.services.prompt_loader import load_prompt

log = structlog.get_logger(__name__)


def _fallback_chapter_output(story: StoryORM) -> IdeationOutput:
    angle = story.selected_angle or "the approved story angle"
    hook = story.story_hook or "the approved hook"
    return IdeationOutput(
        assistant_message="I drafted a clear chapter structure. We can refine the order, stakes, or evidence beats from here.",
        decided_tone=normalise_story_tone(story.tone),
        target_duration_minutes=normalise_target_duration(story.target_duration_minutes),
        chapters=[
            IdeationChapterOutput(
                chapter_number=1,
                title="The Hook",
                purpose="Open with the surprise, stakes, and central question.",
                key_points=[angle, hook],
            ),
            IdeationChapterOutput(
                chapter_number=2,
                title="How We Got Here",
                purpose="Explain the origin decisions and forces behind the current moment.",
                key_points=["Build the timeline.", "Name the incentives or constraints."],
            ),
            IdeationChapterOutput(
                chapter_number=3,
                title="The Evidence",
                purpose="Pressure-test the idea with data, characters, process, and visual proof.",
                key_points=["Identify the strongest facts.", "Clarify whose story makes the stakes visible."],
            ),
            IdeationChapterOutput(
                chapter_number=4,
                title="The Payoff",
                purpose="Resolve the central question and leave the viewer with what changes next.",
                key_points=["Return to the opening tension.", "Name the forward-looking consequence."],
            ),
        ],
    )


class ChapterWriterAgent(ChapterStructureSkill):
    """
    Canonical chapter/story-structure agent.

    In ideation it drafts editable chapter outlines. In the production graph it
    uses the inherited storyline-creator implementation to turn approved
    planning artifacts into a duration-fit act structure for the scriptwriter.
    """

    prompt_name = "chapter_writer"
    reference_role = "chapter_writer"
    duration_role_name = "Chapter Writer"

    def __init__(self) -> None:
        super().__init__()
        _llm = ChatAnthropic(
            model=settings.claude_haiku_model,
            api_key=settings.anthropic_api_key,
            max_tokens=2200,
            temperature=0.3,
        )
        self._chapter_structured_llm = _llm.with_structured_output(IdeationOutput)

    async def plan_chapters(
        self,
        *,
        story: StoryORM,
        user_message: str,
        fresh_research_context: str = "",
    ) -> IdeationOutput:
        """Generate or refine the editable chapter outline before scripting."""
        reference_pack = get_reference_pack(
            role="chapter_writer",
            topic=story.topic,
            state={
                "selected_angle": story.selected_angle,
                "story_hook": story.story_hook,
                "chapters_data": story.chapters_data or [],
            },
            max_cards=5,
            token_budget=1500,
        )
        reference_context = format_reference_pack(reference_pack)
        prompt = (
            "Active stage: chapters. Return a chapter outline only. Each chapter needs "
            "a title, purpose, and key points. Do not write narration or final script copy.\n\n"
            f"=== CURRENT STORY CONTEXT ===\n{compact_ideation_context(story)}\n\n"
            f"=== RECENT CHAT ===\n"
            + "\n".join(
                f"{item.get('role', 'user')}: {str(item.get('content', ''))[:600]}"
                for item in (story.ideation_chat_data or [])[-10:]
                if isinstance(item, dict)
            )
            + "\n\n"
            f"=== FRESH RESEARCH CONTEXT ===\n{fresh_research_context or 'No fresh research was fetched for this turn.'}\n\n"
            f"{reference_context}\n\n"
            f"User request: {user_message}\n\n"
            "Also keep or adjust the backend-decided tone and target duration as 5, 10, or 15 minutes."
        )

        try:
            output: IdeationOutput = await self._chapter_structured_llm.ainvoke(
                [SystemMessage(content=load_prompt("chapter_writer")), HumanMessage(content=prompt)]
            )
        except Exception as exc:
            log.warning("chapter_writer.fallback", story_id=str(story.id), error=str(exc))
            output = _fallback_chapter_output(story)

        output.decided_tone = normalise_story_tone(output.decided_tone)
        output.target_duration_minutes = normalise_target_duration(output.target_duration_minutes)
        return output


__all__ = [
    "ChapterWriterAgent",
    "StoryActOutput",
    "StorylineCreatorOutput",
    "StorylineProposalOutput",
]
