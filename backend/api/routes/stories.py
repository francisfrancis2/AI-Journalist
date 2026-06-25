"""
Stories API routes — CRUD + pipeline trigger + research chat endpoints.
"""

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.angles_and_hooks import (
    AnglesAndHooksAgent,
    IdeationOutput,
    fallback_ideation_output,
)
from backend.agents.chapter_writer import ChapterWriterAgent
from backend.agents.chief_editor_evaluator import ChiefEditorEvaluatorAgent
from backend.agents.scriptwriter import ScriptwriterAgent
from backend.api.deps import get_current_user
from backend.api.security import validate_user_input
from backend.config import settings
from backend.db.database import get_db
from backend.graph.journalist_graph import journalist_graph
from backend.graph.state import create_initial_state
from backend.models.benchmark import BenchmarkReport
from backend.models.research import (
    AnalysisResult,
    EvaluationReport,
    RawSource,
    ResearchPackage,
    StorylineProposal,
)
from backend.models.notification import AdminNotificationORM
from backend.models.story import (
    FinalScript,
    IdeationStage,
    ScriptAuditReport,
    StoryCreate,
    StoryListItem,
    StoryORM,
    StoryRead,
    StoryStatus,
)
from backend.models.user import UserORM
from backend.services.duration_targets import WORDS_PER_MINUTE
from backend.tools.anthropic_search import AnthropicSearchTool
from backend.tools.news_api import NewsAPITool
from backend.tools.web_search import WebSearchTool

log = structlog.get_logger(__name__)
router = APIRouter()
_angles_and_hooks_agent = AnglesAndHooksAgent()
_chapter_writer_agent = ChapterWriterAgent()
_chief_editor_agent = ChiefEditorEvaluatorAgent()


# ── Chat / Research models ────────────────────────────────────────────────────

class ImplementRecommendationsRequest(BaseModel):
    recommendations: list[str] = Field(..., min_length=1, description="Selected recommendation strings to implement")


class SelectAngleRequest(BaseModel):
    selected_angle: str = Field(..., min_length=4, max_length=400, description="The angle text the user picked")


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class YouTubeVideo(BaseModel):
    title: str
    url: str
    channel: str
    description: str


class ChatResponse(BaseModel):
    content: str
    youtube_results: list[YouTubeVideo] = Field(default_factory=list)


class IdeationCreateRequest(BaseModel):
    prompt: str = Field(..., min_length=10, max_length=2000)


class IdeationChapter(BaseModel):
    chapter_number: int
    title: str
    purpose: str
    key_points: list[str] = Field(default_factory=list)


class IdeationAngleDraft(BaseModel):
    angle: str = Field(..., min_length=4, max_length=500)
    framing_axis: str = Field(default="editorial", max_length=80)
    rationale: str = Field(default="", max_length=1000)


class IdeationChatRequest(BaseModel):
    message: str = Field(..., min_length=2, max_length=2000)
    stage: Literal["angles", "hook", "chapters", "script"] | None = None
    angles: list[IdeationAngleDraft] | None = None
    selected_angle: str | None = Field(None, max_length=500)
    story_hook: str | None = Field(None, max_length=900)
    chapters: list[IdeationChapter] | None = None


class ApproveAngleRequest(BaseModel):
    selected_angle: str = Field(..., min_length=4, max_length=500)


class ApproveHookRequest(BaseModel):
    story_hook: str = Field(..., min_length=10, max_length=900)


class ApproveChaptersRequest(BaseModel):
    chapters: list[IdeationChapter] = Field(..., min_length=1)


class IdeationGenerateRequest(BaseModel):
    instruction: str | None = Field(None, max_length=1000)


class IdeationSourceLink(BaseModel):
    title: str
    url: Optional[str] = None
    provider: str = "source"
    preview: str = ""


class IdeationChatResponse(BaseModel):
    story: StoryRead
    content: str
    sources: list[IdeationSourceLink] = Field(default_factory=list)


_SCRIPT_WORD_RE = re.compile(r"\S+")
_IDEATION_EDITABLE_STATUSES = {
    StoryStatus.IDEATING.value,
    StoryStatus.COMPLETED.value,
}

_SCRIPT_GENERATION_OPERATION = "script_generation"
_ANGLE_GENERATION_OPERATIONS = {"initial_angles", "generate_angles"}


def _ensure_ideation_editable(story: StoryORM, action: str) -> None:
    if str(story.status) not in _IDEATION_EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Story is currently {story.status}; {action} is only available for ideating or completed stories.",
        )


def _is_running_operation(story: StoryORM, operation_type: str | None = None) -> bool:
    operation = story.ideation_operation_data or {}
    if operation.get("status") != "running":
        return False
    return operation_type is None or operation.get("type") == operation_type


def _archive_current_script(story: StoryORM, reason: str) -> Optional[list]:
    if not story.script_data:
        return story.script_versions
    versions = [item for item in (story.script_versions or []) if isinstance(item, dict)]
    next_version = len(versions) + 1
    versions.append(
        {
            "version": next_version,
            "script": story.script_data,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
    )
    return versions[-20:]


def _invalidate_current_script_values(story: StoryORM, reason: str) -> dict[str, Any]:
    if not story.script_data:
        return {}
    return {
        "script_versions": _archive_current_script(story, reason),
        "script_data": None,
        "script_audit_data": None,
        "benchmark_data": None,
        "quality_score": None,
        "word_count": None,
        "estimated_duration_minutes": None,
    }


def _script_word_count(value: str) -> int:
    return len(_SCRIPT_WORD_RE.findall(value or ""))


def _normalise_manual_script(story_id: uuid.UUID, payload: FinalScript) -> FinalScript:
    script = payload.model_copy(deep=True)
    script.story_id = story_id
    total_words = (
        _script_word_count(script.logline)
        + _script_word_count(script.opening_hook)
        + _script_word_count(script.closing_statement)
    )
    for index, section in enumerate(script.sections, start=1):
        section.section_number = index
        section_words = _script_word_count(section.narration)
        section.estimated_seconds = round((section_words / WORDS_PER_MINUTE) * 60) if section_words else 0
        total_words += section_words
    script.total_word_count = total_words
    script.estimated_duration_minutes = round(total_words / WORDS_PER_MINUTE, 1) if total_words else 0
    return script


# ── Chat helpers ──────────────────────────────────────────────────────────────

_FRESH_RESEARCH_KEYWORDS = {
    "research",
    "search",
    "find",
    "lookup",
    "look up",
    "source",
    "sources",
    "data",
    "stat",
    "stats",
    "evidence",
    "expert",
    "experts",
    "latest",
    "current",
    "verify",
    "fact",
    "fact-check",
    "evidence",
    "gap",
    "gaps",
    "numbers",
    "news",
}


def _should_fetch_fresh_research(message: str) -> bool:
    lower = message.lower()
    return any(keyword in lower for keyword in _FRESH_RESEARCH_KEYWORDS)


def _ideation_chat_stage(story: StoryORM, requested_stage: str | None) -> IdeationStage:
    """Resolve chat edits to the currently visible page, not just saved workflow state."""
    if requested_stage == "script":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Editorial chat edits are only available for Angle, Hook, and Chapters pages.",
        )
    if requested_stage in {IdeationStage.ANGLES.value, IdeationStage.HOOK.value, IdeationStage.CHAPTERS.value}:
        return IdeationStage(requested_stage)
    stage = IdeationStage(story.ideation_stage or IdeationStage.ANGLES.value)
    return IdeationStage.CHAPTERS if stage == IdeationStage.READY_FOR_SCRIPT else stage


def _normalise_ideation_angle_drafts(angles: list[IdeationAngleDraft]) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in angles:
        angle = " ".join(item.angle.strip().split())
        key = angle.lower()
        if not angle or key in seen:
            continue
        seen.add(key)
        normalised.append(
            {
                "angle": angle,
                "framing_axis": " ".join((item.framing_axis or "editorial").strip().split())[:80],
                "rationale": " ".join((item.rationale or "").strip().split())[:1000],
            }
        )
    return normalised[:8]


def _source_links_from_sources(sources: list[RawSource], limit: int = 12) -> list[IdeationSourceLink]:
    links: list[IdeationSourceLink] = []
    seen: set[str] = set()
    for source in sources:
        key = source.url or source.title.lower()
        if key in seen:
            continue
        seen.add(key)
        provider = source.metadata.get("provider")
        if not provider:
            provider = getattr(source.source_type, "value", str(source.source_type))
        preview = source.content.strip()
        links.append(
            IdeationSourceLink(
                title=source.title or "Untitled source",
                url=source.url,
                provider=str(provider),
                preview=preview[:240] + ("..." if len(preview) > 240 else ""),
            )
        )
        if len(links) >= limit:
            break
    return links


async def _fresh_research_pack(message: str, topic: str) -> tuple[str, list[RawSource], list[IdeationSourceLink]]:
    """Run lightweight live search and return prompt context plus source links."""
    query = f"{topic} {message}".strip()
    fetches: list[tuple[str, Any]] = [
        (
            "tavily",
            WebSearchTool().search(
                query,
                max_results=min(settings.tavily_max_results, 5),
                search_depth=settings.tavily_search_depth,
            ),
        ),
        (
            "newsapi",
            NewsAPITool().search_everything(
                query,
                page_size=min(settings.news_api_page_size, 5),
            ),
        ),
    ]
    if settings.enable_anthropic_search:
        fetches.append(("anthropic_search", AnthropicSearchTool().search(query)))

    results = await asyncio.gather(
        *(fetch for _, fetch in fetches),
        return_exceptions=True,
    )
    sources: list[RawSource] = []
    for (provider, _), result in zip(fetches, results):
        if isinstance(result, Exception):
            log.warning("chat.fresh_research.failed", provider=provider, error=str(result))
            continue
        for candidate in (result if isinstance(result, list) else [result]):
            if isinstance(candidate, RawSource):
                sources.append(candidate)

    seen: set[str] = set()
    lines: list[str] = []
    for source in sources:
        if not isinstance(source, RawSource):
            continue
        key = source.url or source.title.lower()
        if key in seen:
            continue
        seen.add(key)
        source_type = getattr(source.source_type, "value", str(source.source_type))
        credibility = getattr(source.credibility, "value", str(source.credibility))
        provider = source.metadata.get("provider") or source_type
        preview = source.content.strip()
        preview = preview[:420] + ("..." if len(preview) > 420 else "")
        lines.append(
            "\n".join(
                [
                    f"  {len(lines) + 1}. {source.title}",
                    f"     Provider: {provider} | Credibility: {credibility} | URL: {source.url or 'N/A'}",
                    f"     Preview: {preview or 'No preview available'}",
                ]
            )
        )
        if len(lines) >= 12:
            break

    return "\n".join(lines), sources, _source_links_from_sources(sources)


async def _fresh_research_context(message: str, topic: str) -> str:
    """Run lightweight live search for story chat research requests."""
    context, _, _ = await _fresh_research_pack(message, topic)
    return context


def _append_ideation_messages(
    current: Optional[list],
    *,
    user_message: str,
    assistant_message: str,
) -> list[dict[str, str]]:
    history = [item for item in (current or []) if isinstance(item, dict)]
    history.extend(
        [
            {
                "role": "user",
                "content": user_message,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "role": "assistant",
                "content": assistant_message,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ]
    )
    return history[-40:]


def _append_pending_ideation_message(
    current: Optional[list],
    *,
    user_message: str,
) -> list[dict[str, str]]:
    history = [item for item in (current or []) if isinstance(item, dict)]
    history.append(
        {
            "role": "user",
            "content": user_message,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }
    )
    return history[-40:]


def _complete_pending_ideation_message(
    current: Optional[list],
    *,
    assistant_message: str | None = None,
    error_message: str | None = None,
) -> list[dict[str, str]]:
    history = [dict(item) for item in (current or []) if isinstance(item, dict)]
    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        if item.get("role") == "user" and item.get("status") == "running":
            item["status"] = "failed" if error_message else "completed"
            item["completed_at"] = datetime.now(timezone.utc).isoformat()
            if error_message:
                item["error_message"] = error_message
            history[index] = item
            break
    if assistant_message:
        history.append(
            {
                "role": "assistant",
                "content": assistant_message,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "completed",
            }
        )
    return history[-40:]


def _ideation_operation(
    operation_type: str,
    message: str,
    *,
    status_value: str = "running",
    error_message: str | None = None,
) -> dict[str, str | None]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "type": operation_type,
        "status": status_value,
        "message": message,
        "started_at": now,
        "completed_at": None if status_value == "running" else now,
        "error_message": error_message,
    }


async def _run_story_planning_agent(
    *,
    story: StoryORM,
    user_message: str,
    stage: IdeationStage,
    fresh_research_context: str = "",
) -> IdeationOutput:
    """Delegate one planning turn to the correct canonical five-agent role."""
    validate_user_input(user_message, field="message")
    if stage == IdeationStage.CHAPTERS:
        return await _chapter_writer_agent.plan_chapters(
            story=story,
            user_message=user_message,
            fresh_research_context=fresh_research_context,
        )
    return await _angles_and_hooks_agent.run(
        story=story,
        user_message=user_message,
        stage=stage,
        fresh_research_context=fresh_research_context,
    )


def _merge_angle_options(existing: list | None, generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for angle in [*([item for item in (existing or []) if isinstance(item, dict)]), *generated]:
        key = str(angle.get("angle") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(angle)
    return merged[:8]


def _merge_hook_options(existing: list | None, generated: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for hook in [
        *[str(item) for item in (existing or []) if str(item).strip()],
        *generated,
    ]:
        cleaned = " ".join(hook.strip().split())
        key = cleaned.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return merged[:8]


def _ensure_generated_angles(
    *,
    story: StoryORM,
    output: IdeationOutput,
    operation_type: str,
) -> IdeationOutput:
    """Button-driven angle generation must never complete with an empty canvas."""
    if operation_type not in _ANGLE_GENERATION_OPERATIONS or output.angles:
        return output

    fallback = fallback_ideation_output(
        topic=story.topic,
        stage=IdeationStage.ANGLES,
        selected_angle=story.selected_angle,
        hook=story.story_hook,
    )
    output.angles = fallback.angles
    output.assistant_message = (
        f"{output.assistant_message.strip()}\n\n"
        "I also drafted a starting set of broad angle options so the workspace can keep moving. "
        "We can sharpen them once you add a more specific focus, character, place, or source."
    ).strip()
    log.warning(
        "ideation_operation.used_angle_fallback",
        story_id=str(story.id),
        operation_type=operation_type,
    )
    return output


async def _run_ideation_operation(
    *,
    story_id: str,
    user_message: str,
    stage_value: str,
    operation_type: str,
    fetch_research: bool = False,
    selected_angle: str | None = None,
    approved_hook: str | None = None,
) -> None:
    """Finish a persisted ideation operation after the HTTP response returns."""
    from backend.db.database import AsyncSessionLocal

    story_uuid = uuid.UUID(story_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(StoryORM).where(StoryORM.id == story_uuid))
        story = result.scalar_one_or_none()
        if story is None:
            log.warning("ideation_operation.story_missing", story_id=story_id)
            return

    try:
        stage = IdeationStage(stage_value)
        fresh_context = ""
        sources: list[IdeationSourceLink] = []
        if fetch_research:
            fresh_context, _, sources = await _fresh_research_pack(user_message, story.topic)

        output = await _run_story_planning_agent(
            story=story,
            user_message=user_message,
            stage=stage,
            fresh_research_context=fresh_context,
        )
        if stage == IdeationStage.ANGLES:
            output = _ensure_generated_angles(
                story=story,
                output=output,
                operation_type=operation_type,
            )
        values: dict[str, Any] = {
            "ideation_chat_data": _complete_pending_ideation_message(
                story.ideation_chat_data,
                assistant_message=output.assistant_message,
            ),
            "ideation_operation_data": None,
            "error_message": None,
        }
        if operation_type != "chat":
            values["tone"] = output.decided_tone
            values["target_duration_minutes"] = output.target_duration_minutes
        if selected_angle is not None:
            values["selected_angle"] = selected_angle.strip()
            values["ideation_stage"] = IdeationStage.HOOK.value
            values["story_hook"] = None
            values["hook_options_data"] = []
            values["chapters_data"] = None
        if approved_hook is not None:
            values["story_hook"] = approved_hook.strip()
            values["ideation_stage"] = IdeationStage.CHAPTERS.value
        if sources:
            existing_sources = [
                item for item in (story.ideation_research_data or [])
                if isinstance(item, dict)
            ]
            merged_sources: list[dict[str, Any]] = []
            seen_source_keys: set[str] = set()
            for source in [
                *existing_sources,
                *[source.model_dump(mode="json") for source in sources],
            ]:
                key = str(source.get("url") or source.get("title") or "").strip().lower()
                if not key or key in seen_source_keys:
                    continue
                seen_source_keys.add(key)
                merged_sources.append(source)
            values["ideation_research_data"] = merged_sources
        if stage == IdeationStage.ANGLES and output.angles:
            generated_angles = [angle.model_dump(mode="json") for angle in output.angles]
            values["angles_data"] = (
                _merge_angle_options(story.angles_data, generated_angles)
                if operation_type == "generate_angles"
                else generated_angles
            )
            selected_angle_text = " ".join((story.selected_angle or "").strip().split())
            generated_angle_texts = {
                " ".join(str(angle.get("angle") or "").strip().split()).lower()
                for angle in values["angles_data"]
                if isinstance(angle, dict)
            }
            if operation_type != "chat" or not selected_angle_text or selected_angle_text.lower() not in generated_angle_texts:
                values.update(_invalidate_current_script_values(story, "angle_chat_revision"))
                values["selected_angle"] = None
                values["story_hook"] = None
                values["hook_options_data"] = []
                values["chapters_data"] = None
                values["ideation_stage"] = IdeationStage.ANGLES.value
        elif stage == IdeationStage.HOOK and output.story_hook:
            hook_options = output.hook_options or [output.story_hook]
            values["hook_options_data"] = (
                _merge_hook_options(story.hook_options_data, hook_options)
                if operation_type == "generate_hooks"
                else _merge_hook_options([], hook_options)
            )
            values["story_hook"] = output.story_hook
            values["ideation_stage"] = IdeationStage.HOOK.value
            if operation_type == "chat" and output.story_hook.strip() != (story.story_hook or "").strip():
                values.update(_invalidate_current_script_values(story, "hook_chat_revision"))
                values["chapters_data"] = None
        elif stage == IdeationStage.CHAPTERS and output.chapters:
            values["chapters_data"] = [chapter.model_dump(mode="json") for chapter in output.chapters]
            if operation_type == "chat":
                values.update(_invalidate_current_script_values(story, "chapter_chat_revision"))
                values["ideation_stage"] = IdeationStage.CHAPTERS.value

        if operation_type != "chat" and output.title:
            values["title"] = output.title[:512]

        async with AsyncSessionLocal() as db:
            await db.execute(update(StoryORM).where(StoryORM.id == story_uuid).values(**values))
            await db.commit()
        log.info("ideation_operation.completed", story_id=story_id, operation_type=operation_type)

    except Exception as exc:
        error_message = str(exc)
        log.error(
            "ideation_operation.failed",
            story_id=story_id,
            operation_type=operation_type,
            error=error_message,
        )
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(StoryORM).where(StoryORM.id == story_uuid))
            story = result.scalar_one_or_none()
            if story is None:
                return
            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == story_uuid)
                .values(
                    ideation_chat_data=_complete_pending_ideation_message(
                        story.ideation_chat_data,
                        error_message=error_message,
                    ),
                    ideation_operation_data=_ideation_operation(
                        operation_type,
                        user_message,
                        status_value="failed",
                        error_message=error_message,
                    ),
                    error_message=error_message,
                )
            )
            await db.commit()


def _build_chat_system_prompt(story: StoryORM, fresh_research_context: str = "") -> str:
    """Build a rich system prompt from the persisted story artefacts."""
    script_context = ""
    if story.script_data:
        sections = story.script_data.get("sections", [])
        script_lines: list[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            estimated_seconds = section.get("estimated_seconds", 120)
            try:
                estimated_minutes = max(1, int(estimated_seconds) // 60)
            except (TypeError, ValueError):
                estimated_minutes = 2
            source_ids = section.get("source_ids") or []
            if not isinstance(source_ids, list):
                source_ids = []
            narration = str(section.get("narration") or "").strip()
            narration_excerpt = narration[:900] + ("..." if len(narration) > 900 else "")
            script_lines.append(
                "\n".join(
                    [
                        f"  Act {section.get('section_number', '?')}: {section.get('title', 'Untitled')} (~{estimated_minutes} min)",
                        f"    Source IDs: {', '.join(str(source_id) for source_id in source_ids) or 'None'}",
                        f"    Narration excerpt: {narration_excerpt or 'Not available'}",
                    ]
                )
            )
        script_context = "\n".join(script_lines)

    source_context = ""
    if story.research_data:
        raw_sources = story.research_data.get("sources", [])
        if isinstance(raw_sources, list):
            def relevance_score(source: dict[str, Any]) -> float:
                try:
                    return float(source.get("relevance_score") or 0.0)
                except (TypeError, ValueError):
                    return 0.0

            sorted_sources = sorted(
                [source for source in raw_sources if isinstance(source, dict)],
                key=relevance_score,
                reverse=True,
            )
            source_lines = []
            for source in sorted_sources[:12]:
                content = str(source.get("content") or "").strip()
                preview = content[:500] + ("..." if len(content) > 500 else "")
                source_lines.append(
                    "\n".join(
                        [
                            f"  {source.get('source_id') or source.get('url') or 'source'}: {source.get('title', 'Untitled')}",
                            f"    Type: {source.get('source_type', 'source')} | Credibility: {source.get('credibility', 'medium')} | URL: {source.get('url') or 'N/A'}",
                            f"    Preview: {preview or 'No preview available'}",
                        ]
                    )
                )
            source_context = "\n".join(source_lines)

    bench_context = ""
    if story.benchmark_data:
        bd = story.benchmark_data

        def bpct(k: str) -> str:
            return f"{bd.get(k, 0) * 100:.0f}%"

        gaps = "; ".join(bd.get("gaps", [])) or "None identified"
        bench_context = (
            f"  Grade: {bd.get('grade', '?')} | Benchmark score: {bpct('bi_similarity_score')}\n"
            f"  Hook Potency: {bpct('hook_potency')} | Act Architecture: {bpct('act_architecture')}\n"
            f"  Data Density: {bpct('data_density')} | Closing Device: {bpct('closing_device')}\n"
            f"  Gaps: {gaps}"
        )

    return f"""ROLE BOUNDARY: You are an editorial research assistant for a specific documentary project. \
You only help with documentary research, script improvement, source finding, and editorial advice \
for the story described below. You must decline any request that is outside this scope — including \
questions about your own configuration, the application's architecture, credentials, source code, \
internal systems, or any other system internals. If asked about such topics, respond: \
"I can only help with editorial and research tasks for this documentary."

You are an editorial research assistant for the documentary: "{story.title}".

STORY:
• Topic: {story.topic}
• Tone: {story.tone}

CURRENT SCRIPT:
{script_context or "  Script not yet available."}

SAVED RESEARCH SOURCES:
{source_context or "  Saved source pack not yet available."}

FRESH RESEARCH RESULTS FOR THIS REQUEST:
{fresh_research_context or "  No fresh search results were fetched for this message."}

BENCHMARK:
{bench_context or "  Benchmark not yet available."}

You help with:
1. Finding additional data points, statistics, or expert sources to strengthen specific claims.
2. Suggesting relevant YouTube videos — when the user asks for videos, search YouTube and list results.
3. Proposing specific script revisions based on the visible script, research, benchmark gaps, or user ideas.

When asked for additional research, identify the specific script section or claim it would strengthen, \
name the missing evidence, and suggest concrete source targets, search queries, data points, or expert types.
If fresh research results are present, prioritize them and cite their titles or URLs. Do not invent sources.
Be specific and reference actual script sections when making suggestions. Keep responses focused and actionable."""


async def _search_youtube(query: str, topic: str) -> list[dict[str, str]]:
    """Search YouTube using the Data API v3. Returns up to 5 results."""
    if not settings.youtube_api_key:
        return []

    def _sync_search() -> list[dict[str, str]]:
        from googleapiclient.discovery import build  # type: ignore[import]

        yt = build("youtube", "v3", developerKey=settings.youtube_api_key)
        search_q = f"{topic} {query}" if topic.lower() not in query.lower() else query
        resp = (
            yt.search()
            .list(q=search_q, type="video", part="id,snippet", maxResults=5, relevanceLanguage="en")
            .execute()
        )
        results = []
        for item in resp.get("items", []):
            snippet = item["snippet"]
            results.append(
                {
                    "title": snippet["title"],
                    "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                    "channel": snippet["channelTitle"],
                    "description": (snippet.get("description") or "")[:200],
                }
            )
        return results

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_search)
    except Exception as exc:
        log.warning("youtube_search.failed", error=str(exc))
        return []


def _normalise_chat_content(raw: object) -> str:
    """Convert Anthropic/LangChain content blocks into plain text."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif hasattr(block, "text"):
                parts.append(str(getattr(block, "text")))
        return "\n".join(part for part in parts if part).strip()
    return str(raw)


def _evaluation_quality_score(
    evaluation: Optional[EvaluationReport],
    fallback: Optional[float] = None,
) -> Optional[float]:
    """Return a legacy persisted score only when Chief Editor produced one."""
    if evaluation is None:
        return fallback
    return evaluation.overall_score


# ── Background pipeline runner ────────────────────────────────────────────────

_NODE_STATUS_MAP: dict[str, StoryStatus] = {
    "research_agent": StoryStatus.RESEARCHING,
    "angles_and_hooks": StoryStatus.ANALYSING,
    "chapter_writer": StoryStatus.WRITING_STORYLINE,
    "chief_editor_evaluator": StoryStatus.EVALUATING,
    "chief_editor_script_audit": StoryStatus.SCRIPTING,
    "chief_editor_rewrite": StoryStatus.SCRIPTING,
    "scriptwriter": StoryStatus.SCRIPTING,
}

# Ordering used to guard against status regression when the graph is re-driven
# (e.g. resume after angle selection) — only advance forward, never backward.
_STATUS_PHASE_ORDER: dict[StoryStatus, int] = {
    StoryStatus.IDEATING: 0,
    StoryStatus.PENDING: 0,
    StoryStatus.RESEARCHING: 1,
    StoryStatus.ANALYSING: 2,
    StoryStatus.AWAITING_ANGLE_SELECTION: 3,
    StoryStatus.ANGLE_SELECTION_EXPIRED: 7,
    StoryStatus.WRITING_STORYLINE: 4,
    StoryStatus.EVALUATING: 5,
    StoryStatus.SCRIPTING: 6,
    StoryStatus.COMPLETED: 7,
    StoryStatus.FAILED: 7,
}

_TERMINAL_STORY_STATUSES: set[StoryStatus] = {
    StoryStatus.COMPLETED,
    StoryStatus.FAILED,
    StoryStatus.ANGLE_SELECTION_EXPIRED,
}


def _status_for_completed_node(node_name: str, state: dict) -> Optional[StoryStatus]:
    """Decide what status the story should advance to after a node completes."""
    if node_name == "angles_and_hooks" and state.get("generated_angles"):
        # If selected_angle is set (quality-gate restart path), don't pause.
        # The next node will move status forward instead.
        if state.get("selected_angle"):
            return None
        return StoryStatus.AWAITING_ANGLE_SELECTION
    return _NODE_STATUS_MAP.get(node_name)


async def _advance_story_status(story_id: str, new_status: StoryStatus) -> None:
    """Advance status only if the new phase is strictly later than the current one."""
    from backend.db.database import AsyncSessionLocal
    earlier_phases = [
        s.value for s, order in _STATUS_PHASE_ORDER.items()
        if order < _STATUS_PHASE_ORDER[new_status]
    ]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(StoryORM)
            .where(StoryORM.id == uuid.UUID(story_id))
            .where(StoryORM.status.in_(earlier_phases))
            .values(status=new_status)
        )
        await db.commit()


async def _drive_pipeline(story_id: str, state: dict) -> None:
    """
    Stream the journalist graph with the given initial state. Used by both the
    fresh-start path and the resume-after-angle-selection path.

    Handles per-node status advancement (with regression guard), the angle-
    selection pause, the normal completion persistence, and exception fallout.
    """
    from backend.db.database import AsyncSessionLocal

    final_state: dict = dict(state)
    ideation_script_generation = bool(state.get("ideation_script_generation"))
    try:
        async for chunk in journalist_graph.astream(
            state,
            config={"recursion_limit": settings.graph_recursion_limit},
            stream_mode="updates",
        ):
            node_name = next(iter(chunk))
            node_updates = chunk[node_name] or {}
            final_state.update(node_updates)

            new_status = _status_for_completed_node(node_name, final_state)
            if new_status and not ideation_script_generation:
                await _advance_story_status(story_id, new_status)
                log.info("pipeline.node_complete", story_id=story_id, node=node_name, status=new_status)
            elif new_status:
                log.info("pipeline.script_generation_node_complete", story_id=story_id, node=node_name)

    except Exception as exc:
        log.error("pipeline.failed", story_id=story_id, error=str(exc))
        async with AsyncSessionLocal() as db:
            values: dict[str, Any] = {"error_message": str(exc)}
            if ideation_script_generation:
                values["ideation_operation_data"] = _ideation_operation(
                    _SCRIPT_GENERATION_OPERATION,
                    "Script generation failed.",
                    status_value="failed",
                    error_message=str(exc),
                )
            else:
                values["status"] = StoryStatus.FAILED
            await db.execute(update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(**values))
            await db.commit()
        return

    # ── Paused at angle selection ─────────────────────────────────────────────
    # If we have angles but no selection, the graph ended after Angles & Hooks
    # node. Persist research/analysis + angles and exit cleanly; the user will
    # resume via POST /stories/{id}/select-angle.
    if final_state.get("generated_angles") and not final_state.get("selected_angle"):
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(
                    status=StoryStatus.AWAITING_ANGLE_SELECTION,
                    angles_data=final_state["generated_angles"],
                    iteration_count=final_state.get("research_iteration", 0),
                    research_data=(
                        final_state["research_package"].model_dump(mode="json")
                        if final_state.get("research_package") else None
                    ),
                    analysis_data=(
                        final_state["analysis_result"].model_dump(mode="json")
                        if final_state.get("analysis_result") else None
                    ),
                )
            )
            await db.commit()
        log.info(
            "pipeline.awaiting_angle_selection",
            story_id=story_id,
            angle_count=len(final_state["generated_angles"]),
        )
        return

    # ── Normal completion (script produced or genuinely failed downstream) ────
    script: Optional[FinalScript] = final_state.get("final_script")
    evaluation = final_state.get("evaluation_report")

    async with AsyncSessionLocal() as db:
        values: dict[str, Any] = {
            "status": StoryStatus.COMPLETED if script else StoryStatus.FAILED,
            "script_data": script.model_dump(mode="json") if script else None,
            "quality_score": _evaluation_quality_score(evaluation),
            "word_count": script.total_word_count if script else None,
            "estimated_duration_minutes": script.estimated_duration_minutes if script else None,
            "research_data": (
                final_state["research_package"].model_dump(mode="json")
                if final_state.get("research_package") else None
            ),
            "analysis_data": (
                final_state["analysis_result"].model_dump(mode="json")
                if final_state.get("analysis_result") else None
            ),
            "storyline_data": (
                final_state["selected_storyline"].model_dump(mode="json")
                if final_state.get("selected_storyline") else None
            ),
            "evaluation_data": (
                evaluation.model_dump(mode="json") if evaluation else None
            ),
            "iteration_count": final_state.get("research_iteration", 0),
            "error_message": final_state.get("error"),
            "benchmark_data": (
                final_state["benchmark_report"].model_dump(mode="json")
                if final_state.get("benchmark_report") else None
            ),
            "script_audit_data": (
                final_state["script_audit_report"].model_dump(mode="json")
                if final_state.get("script_audit_report") else None
            ),
            "pipeline_cycles_run": max(final_state.get("pipeline_cycle", 0), 1),
            "pipeline_failure_summary": final_state.get("pipeline_failure_summary"),
        }
        if ideation_script_generation:
            values["ideation_operation_data"] = None if script else _ideation_operation(
                _SCRIPT_GENERATION_OPERATION,
                "Script generation failed.",
                status_value="failed",
                error_message=final_state.get("error") or "No final script was produced.",
            )
            if not script:
                values["status"] = StoryStatus.IDEATING
        if script:
            values["title"] = script.title

        await db.execute(
            update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(**values)
        )

        # Create admin notification for technical pipeline failures
        if final_state.get("is_technical_failure") and final_state.get("pipeline_failure_summary"):
            failure_summary = final_state["pipeline_failure_summary"]
            error_detail = final_state.get("error")
            notification = AdminNotificationORM(
                story_id=uuid.UUID(story_id),
                level="error",
                title=f"Pipeline quality failure — technical error (story {story_id[:8]})",
                message=failure_summary,
                technical_detail=error_detail,
                suggested_fix=(
                    "Check API key validity and credit balances for Tavily, NewsAPI, "
                    "Alpha Vantage, and Anthropic. Verify database connectivity."
                ),
            )
            db.add(notification)

        await db.commit()

    log.info("pipeline.complete", story_id=story_id, status=values["status"])


async def _run_pipeline(
    story_id: str,
    topic: str,
    tone: str,
    target_duration_minutes: int,
    target_audience: Optional[str],
) -> None:
    """Fresh-start path. Build initial state and drive the pipeline; may pause at angle selection."""
    log.info("pipeline.started", story_id=story_id)
    initial_state = create_initial_state(
        topic=topic,
        story_id=story_id,
        tone=tone,
        target_duration_minutes=target_duration_minutes,
        target_audience=target_audience,
    )
    await _drive_pipeline(story_id, initial_state)


async def _run_pipeline_from_ideation(story_id: str) -> None:
    """Fresh-start pipeline path seeded with the approved ideation artifacts."""
    from backend.db.database import AsyncSessionLocal

    log.info("pipeline.ideation_started", story_id=story_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(StoryORM).where(StoryORM.id == uuid.UUID(story_id)))
        story = result.scalar_one_or_none()
        if story is None:
            log.error("pipeline.ideation.story_not_found", story_id=story_id)
            return

    if not story.selected_angle or not story.story_hook or not story.chapters_data:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(
                    status=StoryStatus.FAILED,
                    error_message="Approved ideation plan is incomplete.",
                )
            )
            await db.commit()
        return

    state = create_initial_state(
        topic=story.topic,
        story_id=story_id,
        tone=story.tone,
        target_duration_minutes=story.target_duration_minutes,
        target_audience=story.target_audience,
    )
    if story.research_data:
        try:
            state["research_package"] = ResearchPackage(**story.research_data)
            state["research_iteration"] = max(story.iteration_count or 1, 1)
        except Exception as exc:
            log.warning("pipeline.ideation.research_hydration_failed", story_id=story_id, error=str(exc))
    if story.analysis_data:
        try:
            state["analysis_result"] = AnalysisResult(**story.analysis_data)
        except Exception as exc:
            log.warning("pipeline.ideation.analysis_hydration_failed", story_id=story_id, error=str(exc))
    state["selected_angle"] = story.selected_angle
    state["story_hook"] = story.story_hook
    state["chapters_data"] = story.chapters_data
    state["ideation_script_generation"] = True
    state["script_plan_priority"] = (
        "This script was launched from the producer-approved ideation workspace. "
        "Treat the selected angle, approved hook, and approved chapter outline as the primary brief. "
        "Use previous research and analysis first. Additional research may fill evidence gaps, but it must not "
        "replace the approved direction unless a fact directly disproves it."
    )
    await _drive_pipeline(story_id, state)


def _hydrate_state_for_angle_resume(story: StoryORM, selected_angle: str) -> dict[str, Any]:
    """
    Rebuild graph state from the persisted story so the post-angle phase of the
    pipeline can resume. Research and Angles & Hooks nodes skip themselves when
    research_package + analysis_result are present and no improvement plan is set.
    """
    from backend.models.research import ResearchPackage  # local import to avoid cycle
    if not story.research_data or not story.analysis_data:
        raise ValueError("Cannot resume: research_data or analysis_data is missing.")

    state = create_initial_state(
        topic=story.topic,
        story_id=str(story.id),
        tone=story.tone,
        target_duration_minutes=story.target_duration_minutes,
        target_audience=story.target_audience,
    )
    state["research_package"] = ResearchPackage(**story.research_data)
    state["analysis_result"] = AnalysisResult(**story.analysis_data)
    state["generated_angles"] = list(story.angles_data or [])
    state["selected_angle"] = selected_angle
    state["research_iteration"] = story.iteration_count or 1
    return state


async def _run_pipeline_resume_after_angle_selection(story_id: str, selected_angle: str) -> None:
    """Resume the pipeline after the user picks an angle."""
    from backend.db.database import AsyncSessionLocal
    log.info("pipeline.resume_after_angle", story_id=story_id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(StoryORM).where(StoryORM.id == uuid.UUID(story_id)))
        story = result.scalar_one_or_none()
        if story is None:
            log.error("pipeline.resume.story_not_found", story_id=story_id)
            return

    try:
        state = _hydrate_state_for_angle_resume(story, selected_angle)
    except ValueError as exc:
        log.error("pipeline.resume.hydration_failed", story_id=story_id, error=str(exc))
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(status=StoryStatus.FAILED, error_message=str(exc))
            )
            await db.commit()
        return

    await _drive_pipeline(story_id, state)


async def _run_regenerate_angles(story_id: str) -> None:
    """Re-run the Angles & Hooks synthesis step using persisted research."""
    from backend.db.database import AsyncSessionLocal
    from backend.models.research import ResearchPackage

    log.info("pipeline.regenerate_angles.started", story_id=story_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(StoryORM).where(StoryORM.id == uuid.UUID(story_id)))
        story = result.scalar_one_or_none()
        if story is None or not story.research_data or not story.analysis_data:
            log.error("pipeline.regenerate_angles.missing_data", story_id=story_id)
            return

    state = {
        "story_id": story_id,
        "topic": story.topic,
        "tone": story.tone,
        "research_package": ResearchPackage(**story.research_data),
    }
    try:
        updates = await _angles_and_hooks_agent.analyze_research(state)
    except Exception as exc:
        log.error("pipeline.regenerate_angles.error", story_id=story_id, error=str(exc))
        return

    angles = updates.get("generated_angles") or []
    analysis = updates.get("analysis_result")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(StoryORM)
            .where(StoryORM.id == uuid.UUID(story_id))
            .values(
                angles_data=angles,
                selected_angle=None,
                analysis_data=analysis.model_dump(mode="json") if analysis else story.analysis_data,
                status=StoryStatus.AWAITING_ANGLE_SELECTION,
            )
        )
        await db.commit()
    log.info("pipeline.regenerate_angles.complete", story_id=story_id, count=len(angles))


def _hydrate_existing_story_state(story: StoryORM) -> dict[str, Any]:
    """Rebuild enough graph state from persisted JSON to rewrite an existing script."""
    if not story.script_data:
        raise ValueError("Story has no script to rewrite.")
    if not story.analysis_data or not story.research_data:
        raise ValueError("Story needs persisted analysis and research data before rewrite.")

    return {
        **create_initial_state(
            topic=story.topic,
            story_id=str(story.id),
            tone=story.tone,
            target_duration_minutes=story.target_duration_minutes,
            target_audience=story.target_audience,
        ),
        "final_script": FinalScript(**story.script_data),
        "script_audit_report": (
            ScriptAuditReport(**story.script_audit_data)
            if story.script_audit_data else None
        ),
        "analysis_result": AnalysisResult(**story.analysis_data),
        "research_package": ResearchPackage(**story.research_data),
        "selected_storyline": (
            StorylineProposal(**story.storyline_data)
            if story.storyline_data else None
        ),
        "evaluation_report": (
            EvaluationReport(**story.evaluation_data)
            if story.evaluation_data else None
        ),
        "benchmark_report": (
            BenchmarkReport(**story.benchmark_data)
            if story.benchmark_data else None
        ),
    }


async def _clone_story_for_revision(
    source: StoryORM,
    db: AsyncSession,
    status: StoryStatus,
    *,
    carry_outputs: bool = True,
) -> StoryORM:
    """Create a new story row pre-populated from source, with a versioned title."""
    root_id = source.parent_story_id or source.id
    result = await db.execute(
        select(StoryORM).where(
            (StoryORM.parent_story_id == root_id) | (StoryORM.id == root_id)
        )
    )
    sibling_count = len(result.scalars().all())
    new_revision = sibling_count + 1

    base_title = source.title
    import re as _re
    base_title = _re.sub(r"\s+v\d+$", "", base_title).strip()
    new_title = f"{base_title} v{new_revision}"

    clone = StoryORM(
        title=new_title,
        topic=source.topic,
        status=status,
        tone=source.tone,
        target_duration_minutes=source.target_duration_minutes,
        target_audience=source.target_audience,
        owner_user_id=source.owner_user_id,
        research_data=source.research_data,
        analysis_data=source.analysis_data,
        storyline_data=source.storyline_data,
        evaluation_data=source.evaluation_data if carry_outputs else None,
        script_data=source.script_data if carry_outputs else None,
        script_audit_data=source.script_audit_data if carry_outputs else None,
        benchmark_data=source.benchmark_data if carry_outputs else None,
        quality_score=source.quality_score if carry_outputs else None,
        word_count=source.word_count if carry_outputs else None,
        estimated_duration_minutes=source.estimated_duration_minutes if carry_outputs else None,
        iteration_count=source.iteration_count,
        parent_story_id=root_id,
        revision=new_revision,
    )
    db.add(clone)
    await db.commit()
    await db.refresh(clone)
    return clone


async def _run_manual_script_rewrite(story_id: str, source_story_id: str) -> None:
    """Run a single audit-driven rewrite, writing results into a new story row."""
    from backend.db.database import AsyncSessionLocal

    log.info("manual_rewrite.started", story_id=story_id, source=source_story_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(StoryORM).where(StoryORM.id == uuid.UUID(story_id)))
        story = result.scalar_one_or_none()
        if not story:
            log.warning("manual_rewrite.story_missing", story_id=story_id)
            return
        try:
            state = _hydrate_existing_story_state(story)
            if state.get("script_audit_report") is None:
                state.update(await _chief_editor_agent.audit_script(state))
            state.update(await _chief_editor_agent.rewrite_script(state))
            state.update(await _chief_editor_agent.audit_script(state))

            script: FinalScript = state["final_script"]
            audit = state.get("script_audit_report")
            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(
                    status=StoryStatus.COMPLETED,
                    title=script.title,
                    script_data=script.model_dump(mode="json"),
                    word_count=script.total_word_count,
                    estimated_duration_minutes=script.estimated_duration_minutes,
                    script_audit_data=(
                        audit.model_dump(mode="json") if audit else story.script_audit_data
                    ),
                    error_message=None,
                )
            )
            await db.commit()
        except Exception as exc:
            log.error("manual_rewrite.failed", story_id=story_id, error=str(exc))
            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(status=StoryStatus.FAILED, error_message=str(exc))
            )
            await db.commit()

    log.info("manual_rewrite.complete", story_id=story_id)


async def _run_implement_recommendations(story_id: str, source_story_id: str, recommendations: list[str]) -> None:
    """Rebuild storyline + script to implement selected benchmark recommendations."""
    from backend.db.database import AsyncSessionLocal

    log.info("implement_recs.started", story_id=story_id, count=len(recommendations))
    async with AsyncSessionLocal() as db:
        revision_result = await db.execute(select(StoryORM).where(StoryORM.id == uuid.UUID(story_id)))
        revision_story = revision_result.scalar_one_or_none()
        source_result = await db.execute(select(StoryORM).where(StoryORM.id == uuid.UUID(source_story_id)))
        source_story = source_result.scalar_one_or_none()
        if not revision_story or not source_story:
            log.warning("implement_recs.story_missing", story_id=story_id, source_story_id=source_story_id)
            return
        if not source_story.research_data:
            log.warning("implement_recs.source_missing_research", story_id=story_id, source_story_id=source_story_id)
            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(status=StoryStatus.FAILED, error_message="No research data available to rebuild from.")
            )
            await db.commit()
            return

        await db.execute(
            update(StoryORM)
            .where(StoryORM.id == uuid.UUID(story_id))
            .values(status=StoryStatus.WRITING_STORYLINE, error_message=None)
        )
        await db.commit()

        try:
            state = create_initial_state(
                topic=source_story.topic,
                story_id=str(revision_story.id),
                tone=source_story.tone,
                target_duration_minutes=source_story.target_duration_minutes,
                target_audience=source_story.target_audience,
            )
            state["research_package"] = ResearchPackage(**source_story.research_data)
            state["analysis_result"] = (
                AnalysisResult(**source_story.analysis_data)
                if source_story.analysis_data else None
            )
            state["selected_storyline"] = (
                StorylineProposal(**source_story.storyline_data)
                if source_story.storyline_data else None
            )
            state["evaluation_report"] = (
                EvaluationReport(**source_story.evaluation_data)
                if source_story.evaluation_data else None
            )
            state["benchmark_report"] = (
                BenchmarkReport(**source_story.benchmark_data)
                if source_story.benchmark_data else None
            )
            state["user_rewrite_recommendations"] = recommendations
            state["refinement_cycle"] = 1 if state.get("evaluation_report") else 0

            if state.get("analysis_result") is None:
                await db.execute(
                    update(StoryORM)
                    .where(StoryORM.id == uuid.UUID(story_id))
                    .values(status=StoryStatus.ANALYSING)
                )
                await db.commit()
                state.update(await _angles_and_hooks_agent.analyze_research(state))

            state.update(await _chapter_writer_agent.run(state))

            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(status=StoryStatus.EVALUATING)
            )
            await db.commit()
            state.update(await _chief_editor_agent.evaluate_story_plan(state))

            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(status=StoryStatus.SCRIPTING)
            )
            await db.commit()

            state.update(await ScriptwriterAgent().run(state))
            state.update(await _chief_editor_agent.audit_script(state))

            script: FinalScript = state["final_script"]
            audit = state.get("script_audit_report")
            evaluation = state.get("evaluation_report")
            benchmark = state.get("benchmark_report")
            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(
                    status=StoryStatus.COMPLETED,
                    title=script.title,
                    script_data=script.model_dump(mode="json"),
                    analysis_data=(
                        state["analysis_result"].model_dump(mode="json")
                        if state.get("analysis_result") else source_story.analysis_data
                    ),
                    storyline_data=(
                        state["selected_storyline"].model_dump(mode="json")
                        if state.get("selected_storyline") else source_story.storyline_data
                    ),
                    evaluation_data=(
                        evaluation.model_dump(mode="json")
                        if evaluation else source_story.evaluation_data
                    ),
                    benchmark_data=(
                        benchmark.model_dump(mode="json")
                        if benchmark else source_story.benchmark_data
                    ),
                    word_count=script.total_word_count,
                    estimated_duration_minutes=script.estimated_duration_minutes,
                    script_audit_data=(
                        audit.model_dump(mode="json")
                        if audit else source_story.script_audit_data
                    ),
                    quality_score=_evaluation_quality_score(evaluation, source_story.quality_score),
                    error_message=None,
                )
            )
            await db.commit()
            log.info("implement_recs.complete", story_id=story_id)

        except Exception as exc:
            log.error("implement_recs.failed", story_id=story_id, error=str(exc))
            async with AsyncSessionLocal() as err_db:
                await err_db.execute(
                    update(StoryORM)
                    .where(StoryORM.id == uuid.UUID(story_id))
                    .values(status=StoryStatus.FAILED, error_message=str(exc))
                )
                await err_db.commit()


async def _run_script_regeneration(story_id: str) -> None:
    """Re-run the full pipeline from Chapter Writer onward using updated research data."""
    from backend.db.database import AsyncSessionLocal

    log.info("regenerate.started", story_id=story_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(StoryORM).where(StoryORM.id == uuid.UUID(story_id)))
        story = result.scalar_one_or_none()
        if not story:
            log.warning("regenerate.story_missing", story_id=story_id)
            return

        await db.execute(
            update(StoryORM)
            .where(StoryORM.id == uuid.UUID(story_id))
            .values(status=StoryStatus.ANALYSING, error_message=None)
        )
        await db.commit()

        try:
            state: dict[str, Any] = {
                **create_initial_state(
                    topic=story.topic,
                    story_id=str(story.id),
                    tone=story.tone,
                    target_duration_minutes=story.target_duration_minutes,
                    target_audience=story.target_audience,
                ),
                "research_package": ResearchPackage(**story.research_data),
                "analysis_result": AnalysisResult(**story.analysis_data) if story.analysis_data else None,
                "evaluation_report": EvaluationReport(**story.evaluation_data) if story.evaluation_data else None,
                "benchmark_report": BenchmarkReport(**story.benchmark_data) if story.benchmark_data else None,
            }

            # Re-analyse with updated research data
            await db.execute(update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(status=StoryStatus.ANALYSING))
            await db.commit()
            state.update(await _angles_and_hooks_agent.analyze_research(state))

            # Re-build storyline
            await db.execute(update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(status=StoryStatus.WRITING_STORYLINE))
            await db.commit()
            state.update(await _chapter_writer_agent.run(state))

            # Evaluate
            await db.execute(update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(status=StoryStatus.EVALUATING))
            await db.commit()
            state.update(await _chief_editor_agent.evaluate_story_plan(state))

            # Write script
            await db.execute(update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(status=StoryStatus.SCRIPTING))
            await db.commit()
            state.update(await ScriptwriterAgent().run(state))
            state.update(await _chief_editor_agent.audit_script(state))

            script: FinalScript = state["final_script"]
            audit = state.get("script_audit_report")
            evaluation = state.get("evaluation_report")
            benchmark = state.get("benchmark_report")

            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(
                    status=StoryStatus.COMPLETED,
                    title=script.title,
                    script_data=script.model_dump(mode="json"),
                    analysis_data=state["analysis_result"].model_dump(mode="json") if state.get("analysis_result") else story.analysis_data,
                    storyline_data=state["selected_storyline"].model_dump(mode="json") if state.get("selected_storyline") else story.storyline_data,
                    evaluation_data=evaluation.model_dump(mode="json") if evaluation else story.evaluation_data,
                    benchmark_data=benchmark.model_dump(mode="json") if benchmark else story.benchmark_data,
                    script_audit_data=audit.model_dump(mode="json") if audit else story.script_audit_data,
                    word_count=script.total_word_count,
                    estimated_duration_minutes=script.estimated_duration_minutes,
                    quality_score=_evaluation_quality_score(evaluation, story.quality_score),
                    error_message=None,
                )
            )
            await db.commit()
            log.info("regenerate.complete", story_id=story_id)

        except Exception as exc:
            log.error("regenerate.failed", story_id=story_id, error=str(exc))
            async with AsyncSessionLocal() as err_db:
                await err_db.execute(
                    update(StoryORM)
                    .where(StoryORM.id == uuid.UUID(story_id))
                    .values(status=StoryStatus.FAILED, error_message=str(exc))
                )
                await err_db.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _apply_story_access_scope(stmt, current_user: UserORM):
    if current_user.is_admin:
        return stmt
    return stmt.where(StoryORM.owner_user_id == current_user.id)


def _attach_story_owner(story: StoryORM, owner_email: Optional[str]) -> StoryORM:
    setattr(story, "owner_email", owner_email)
    return story


async def _get_story_for_user(
    db: AsyncSession,
    *,
    story_id: uuid.UUID,
    current_user: UserORM,
    include_owner: bool = False,
) -> StoryORM:
    if include_owner:
        stmt = (
            select(StoryORM, UserORM.email)
            .outerjoin(UserORM, StoryORM.owner_user_id == UserORM.id)
            .where(StoryORM.id == story_id)
        )
        stmt = _apply_story_access_scope(stmt, current_user)
        result = await db.execute(stmt)
        row = result.first()
        if not row:
            raise HTTPException(status_code=404, detail=f"Story {story_id} not found")
        story, owner_email = row
        return _attach_story_owner(story, owner_email)

    stmt = _apply_story_access_scope(
        select(StoryORM).where(StoryORM.id == story_id),
        current_user,
    )
    result = await db.execute(stmt)
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status_code=404, detail=f"Story {story_id} not found")
    return story


@router.post("/ideation", response_model=IdeationChatResponse, status_code=status.HTTP_201_CREATED)
async def create_ideation_story(
    payload: IdeationCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeationChatResponse:
    """Create a draft story and queue the first set of editorial angles."""
    validate_user_input(payload.prompt, field="prompt")
    prompt = payload.prompt.strip()
    story = StoryORM(
        title=f"Story: {prompt[:80]}",
        topic=prompt,
        status=StoryStatus.IDEATING,
        tone="explanatory",
        target_duration_minutes=10,
        owner_user_id=current_user.id,
        ideation_stage=IdeationStage.ANGLES.value,
        ideation_chat_data=_append_pending_ideation_message([], user_message=prompt),
        ideation_research_data=[],
        ideation_operation_data=_ideation_operation(
            "initial_angles",
            "Researching the first set of angles.",
        ),
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)
    background_tasks.add_task(
        _run_ideation_operation,
        story_id=str(story.id),
        user_message=f"Generate the first set of producer-selectable documentary angles for this story idea: {prompt}",
        stage_value=IdeationStage.ANGLES.value,
        operation_type="initial_angles",
        fetch_research=True,
    )
    _attach_story_owner(story, current_user.email)
    return IdeationChatResponse(
        story=StoryRead.model_validate(story),
        content="Researching the first set of angles.",
        sources=[],
    )


@router.post("/{story_id}/ideation/chat", response_model=IdeationChatResponse)
async def chat_with_ideation_story(
    story_id: uuid.UUID,
    payload: IdeationChatRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeationChatResponse:
    """Queue a stage-aware chat turn for the current ideation artifact."""
    story = await _get_story_for_user(
        db,
        story_id=story_id,
        current_user=current_user,
        include_owner=True,
    )
    _ensure_ideation_editable(story, "ideation chat")
    stage = _ideation_chat_stage(story, payload.stage)
    if (story.ideation_operation_data or {}).get("status") == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An ideation request is already running for this story.",
        )
    message = payload.message.strip()
    values: dict[str, Any] = {
        "status": StoryStatus.IDEATING,
        "ideation_chat_data": _append_pending_ideation_message(
            story.ideation_chat_data,
            user_message=message,
        ),
        "ideation_operation_data": _ideation_operation(
            "chat",
            message,
        ),
        "error_message": None,
    }
    if stage == IdeationStage.ANGLES:
        if payload.angles is not None:
            values["angles_data"] = _normalise_ideation_angle_drafts(payload.angles)
        if payload.selected_angle is not None:
            angle = " ".join(payload.selected_angle.strip().split())
            previous_angle = (story.selected_angle or "").strip()
            values["selected_angle"] = angle or None
            if angle != previous_angle:
                values.update(_invalidate_current_script_values(story, "angle_chat_revision"))
                values["story_hook"] = None
                values["hook_options_data"] = []
                values["chapters_data"] = None
                values["ideation_stage"] = IdeationStage.ANGLES.value
    elif stage == IdeationStage.HOOK:
        if payload.story_hook is not None:
            hook = " ".join(payload.story_hook.strip().split())
            if hook and len(hook.split()) > 100:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Story hook cannot exceed 100 words.",
                )
            previous_hook = (story.story_hook or "").strip()
            values["story_hook"] = hook or None
            if hook != previous_hook:
                values.update(_invalidate_current_script_values(story, "hook_chat_revision"))
                values["chapters_data"] = None
                values["ideation_stage"] = IdeationStage.HOOK.value
    elif payload.chapters is not None and stage == IdeationStage.CHAPTERS:
        values["chapters_data"] = [
            chapter.model_dump(mode="json") for chapter in payload.chapters
        ]
        values["ideation_stage"] = IdeationStage.CHAPTERS.value
        values.update(_invalidate_current_script_values(story, "chapter_chat_revision"))
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(**values)
    )
    await db.commit()
    await db.refresh(story)
    background_tasks.add_task(
        _run_ideation_operation,
        story_id=str(story_id),
        user_message=message,
        stage_value=stage.value,
        operation_type="chat",
        fetch_research=_should_fetch_fresh_research(message),
    )
    return IdeationChatResponse(
        story=StoryRead.model_validate(story),
        content="Working on your request.",
        sources=[],
    )


@router.post("/{story_id}/ideation/generate-angles", response_model=IdeationChatResponse)
async def generate_more_ideation_angles(
    story_id: uuid.UUID,
    payload: IdeationGenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeationChatResponse:
    """Queue additional angle options and move the workspace back to angle selection."""
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user, include_owner=True)
    _ensure_ideation_editable(story, "angle generation")
    if (story.ideation_operation_data or {}).get("status") == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An ideation request is already running.")
    instruction = (payload.instruction or "").strip()
    user_message = instruction or "Generate three additional producer-selectable story angles that differ from the current options."
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(
            **_invalidate_current_script_values(story, "angle_generation_revision"),
            status=StoryStatus.IDEATING,
            selected_angle=None,
            story_hook=None,
            hook_options_data=[],
            chapters_data=None,
            ideation_stage=IdeationStage.ANGLES.value,
            ideation_chat_data=_append_pending_ideation_message(
                story.ideation_chat_data,
                user_message="Generate more angle options.",
            ),
            ideation_operation_data=_ideation_operation(
                "generate_angles",
                "Generating more angle options.",
            ),
            error_message=None,
        )
    )
    await db.commit()
    await db.refresh(story)
    background_tasks.add_task(
        _run_ideation_operation,
        story_id=str(story_id),
        user_message=user_message,
        stage_value=IdeationStage.ANGLES.value,
        operation_type="generate_angles",
        fetch_research=_should_fetch_fresh_research(user_message),
    )
    return IdeationChatResponse(story=StoryRead.model_validate(story), content="Generating more angle options.")


@router.post("/{story_id}/ideation/generate-hooks", response_model=IdeationChatResponse)
async def generate_more_ideation_hooks(
    story_id: uuid.UUID,
    payload: IdeationGenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeationChatResponse:
    """Queue additional hook options for the current selected angle."""
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user, include_owner=True)
    _ensure_ideation_editable(story, "hook generation")
    if (story.ideation_operation_data or {}).get("status") == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An ideation request is already running.")
    if not story.selected_angle:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Select an angle before generating hooks.")
    instruction = (payload.instruction or "").strip()
    user_message = instruction or (
        "Generate three additional story hook options under 100 words each for the selected angle. "
        "Make them distinct in tension and opening promise."
    )
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(
            **_invalidate_current_script_values(story, "hook_generation_revision"),
            status=StoryStatus.IDEATING,
            chapters_data=None,
            ideation_stage=IdeationStage.HOOK.value,
            ideation_chat_data=_append_pending_ideation_message(
                story.ideation_chat_data,
                user_message="Generate more hook options.",
            ),
            ideation_operation_data=_ideation_operation(
                "generate_hooks",
                "Generating more hook options.",
            ),
            error_message=None,
        )
    )
    await db.commit()
    await db.refresh(story)
    background_tasks.add_task(
        _run_ideation_operation,
        story_id=str(story_id),
        user_message=user_message,
        stage_value=IdeationStage.HOOK.value,
        operation_type="generate_hooks",
        fetch_research=_should_fetch_fresh_research(user_message),
    )
    return IdeationChatResponse(story=StoryRead.model_validate(story), content="Generating more hook options.")


@router.post("/{story_id}/ideation/approve-angle", response_model=IdeationChatResponse)
async def approve_ideation_angle(
    story_id: uuid.UUID,
    payload: ApproveAngleRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeationChatResponse:
    """Approve an angle and queue the initial story hook for the next page."""
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user, include_owner=True)
    _ensure_ideation_editable(story, "angle approval")
    if (story.ideation_operation_data or {}).get("status") == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An ideation request is already running.")
    angle = payload.selected_angle.strip()
    user_message = f"Use this selected angle and draft a story hook: {angle}"
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(
            **_invalidate_current_script_values(story, "angle_revision"),
            status=StoryStatus.IDEATING,
            selected_angle=angle,
            story_hook=None,
            hook_options_data=[],
            chapters_data=None,
            ideation_stage=IdeationStage.HOOK.value,
            ideation_chat_data=_append_pending_ideation_message(
                story.ideation_chat_data,
                user_message=f"Approved angle: {angle}",
            ),
            ideation_operation_data=_ideation_operation(
                "approve_angle",
                "Drafting the story hook.",
            ),
            error_message=None,
        )
    )
    await db.commit()
    await db.refresh(story)
    background_tasks.add_task(
        _run_ideation_operation,
        story_id=str(story_id),
        user_message=user_message,
        stage_value=IdeationStage.HOOK.value,
        operation_type="approve_angle",
        selected_angle=angle,
    )
    return IdeationChatResponse(story=StoryRead.model_validate(story), content="Drafting the story hook.")


@router.post("/{story_id}/ideation/approve-hook", response_model=IdeationChatResponse)
async def approve_ideation_hook(
    story_id: uuid.UUID,
    payload: ApproveHookRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeationChatResponse:
    """Approve a hook and queue the initial chapter outline for the next page."""
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user, include_owner=True)
    _ensure_ideation_editable(story, "hook approval")
    if (story.ideation_operation_data or {}).get("status") == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An ideation request is already running.")
    hook_words = payload.story_hook.strip().split()
    if len(hook_words) > 100:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Story hook cannot exceed 100 words.")
    hook = payload.story_hook.strip()
    user_message = f"Use this approved hook and draft the chapter outline: {hook}"
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(
            **_invalidate_current_script_values(story, "hook_revision"),
            status=StoryStatus.IDEATING,
            story_hook=hook,
            chapters_data=None,
            ideation_stage=IdeationStage.CHAPTERS.value,
            ideation_chat_data=_append_pending_ideation_message(
                story.ideation_chat_data,
                user_message="Approved story hook.",
            ),
            ideation_operation_data=_ideation_operation(
                "approve_hook",
                "Drafting the chapter outline.",
            ),
            error_message=None,
        )
    )
    await db.commit()
    await db.refresh(story)
    background_tasks.add_task(
        _run_ideation_operation,
        story_id=str(story_id),
        user_message=user_message,
        stage_value=IdeationStage.CHAPTERS.value,
        operation_type="approve_hook",
        approved_hook=hook,
    )
    return IdeationChatResponse(story=StoryRead.model_validate(story), content="Drafting the chapter outline.")


@router.post("/{story_id}/ideation/approve-chapters", response_model=StoryRead)
async def approve_ideation_chapters(
    story_id: uuid.UUID,
    payload: ApproveChaptersRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> StoryORM:
    """Approve the chapter outline and mark the ideation plan ready for script generation."""
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user, include_owner=True)
    _ensure_ideation_editable(story, "chapter approval")
    if (story.ideation_operation_data or {}).get("status") == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An ideation request is already running.")
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(
            **_invalidate_current_script_values(story, "chapter_revision"),
            status=StoryStatus.IDEATING,
            chapters_data=[chapter.model_dump(mode="json") for chapter in payload.chapters],
            ideation_stage=IdeationStage.READY_FOR_SCRIPT.value,
        )
    )
    await db.commit()
    await db.refresh(story)
    return story


@router.post("/{story_id}/ideation/generate-script", response_model=StoryRead, status_code=status.HTTP_202_ACCEPTED)
async def generate_script_from_ideation(
    story_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> StoryORM:
    """Launch the full script pipeline from an approved ideation plan."""
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user, include_owner=True)
    _ensure_ideation_editable(story, "script generation")
    if _is_running_operation(story, _SCRIPT_GENERATION_OPERATION):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The script is already being generated.")
    if _is_running_operation(story):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Wait for the current ideation request to finish before generating the script.")
    if not story.selected_angle or not story.story_hook or not story.chapters_data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approve an angle, story hook, and chapters before generating the script.",
        )
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(
            script_versions=_archive_current_script(story, "script_regeneration"),
            status=StoryStatus.IDEATING,
            ideation_stage=IdeationStage.READY_FOR_SCRIPT.value,
            ideation_operation_data=_ideation_operation(
                _SCRIPT_GENERATION_OPERATION,
                "Generating the final script.",
            ),
            error_message=None,
            script_data=None,
            script_audit_data=None,
            quality_score=None,
            word_count=None,
            estimated_duration_minutes=None,
        )
    )
    await db.commit()
    await db.refresh(story)
    background_tasks.add_task(_run_pipeline_from_ideation, story_id=str(story_id))
    return story


@router.post("", response_model=StoryRead, status_code=status.HTTP_202_ACCEPTED)
async def create_story(
    payload: StoryCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> StoryORM:
    """
    Create a new story record and launch the AI journalist pipeline in the background.

    The pipeline is asynchronous — poll ``GET /stories/{id}`` for status updates.
    """
    story = StoryORM(
        title=payload.title or f"Story: {payload.topic[:80]}",
        topic=payload.topic,
        status=StoryStatus.PENDING,
        tone=payload.tone,
        target_duration_minutes=payload.target_duration_minutes,
        target_audience=payload.target_audience.strip() if payload.target_audience else None,
        owner_user_id=current_user.id,
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)
    _attach_story_owner(story, current_user.email)

    background_tasks.add_task(
        _run_pipeline,
        story_id=str(story.id),
        topic=story.topic,
        tone=story.tone,
        target_duration_minutes=story.target_duration_minutes,
        target_audience=story.target_audience,
    )

    log.info("stories.created", story_id=str(story.id), topic=story.topic)
    return story


@router.get("", response_model=list[StoryListItem])
async def list_stories(
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[StoryStatus] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: UserORM = Depends(get_current_user),
) -> list[StoryORM]:
    """List all stories with optional status filter and pagination."""
    stmt = (
        select(StoryORM, UserORM.email)
        .outerjoin(UserORM, StoryORM.owner_user_id == UserORM.id)
        .order_by(StoryORM.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    stmt = _apply_story_access_scope(stmt, current_user)
    if status_filter:
        stmt = stmt.where(StoryORM.status == status_filter)
    result = await db.execute(stmt)
    stories: list[StoryORM] = []
    for story, owner_email in result.all():
        stories.append(_attach_story_owner(story, owner_email))
    return stories


@router.get("/{story_id}", response_model=StoryRead)
async def get_story(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> StoryORM:
    """Retrieve a single story by ID including all pipeline artefacts."""
    return await _get_story_for_user(
        db,
        story_id=story_id,
        current_user=current_user,
        include_owner=True,
    )


@router.get("/{story_id}/script", response_model=FinalScript)
async def get_script(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> FinalScript:
    """Return the final production script for a completed story."""
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user)
    if not story.script_data:
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail=f"Script not yet available. Current status: {story.status}",
        )
    return FinalScript(**story.script_data)


@router.put("/{story_id}/script", response_model=FinalScript)
async def update_script(
    story_id: uuid.UUID,
    payload: FinalScript,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> FinalScript:
    """Persist manual edits to the final script."""
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user)
    if not story.script_data:
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail="Script is not available yet.",
        )
    script = _normalise_manual_script(story_id, payload)
    if not script.title.strip():
        script.title = story.title
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(
            title=script.title[:512],
            status=StoryStatus.COMPLETED,
            script_data=script.model_dump(mode="json"),
            script_versions=_archive_current_script(story, "manual_script_edit"),
            word_count=script.total_word_count,
            estimated_duration_minutes=script.estimated_duration_minutes,
            error_message=None,
        )
    )
    await db.commit()
    return script


@router.get("/{story_id}/events")
async def stream_story_events(
    story_id: uuid.UUID,
    current_user: UserORM = Depends(get_current_user),
) -> StreamingResponse:
    """Stream story status snapshots until the story reaches a terminal state."""
    from backend.db.database import AsyncSessionLocal

    async def _events():
        last_payload: str | None = None
        while True:
            async with AsyncSessionLocal() as session:
                stmt = (
                    select(StoryORM, UserORM.email)
                    .outerjoin(UserORM, StoryORM.owner_user_id == UserORM.id)
                    .where(StoryORM.id == story_id)
                )
                stmt = _apply_story_access_scope(stmt, current_user)
                result = await session.execute(stmt)
                row = result.first()
                if not row:
                    yield "event: error\ndata: {\"detail\":\"Story not found\"}\n\n"
                    return
                story, owner_email = row
                story = _attach_story_owner(story, owner_email)
                payload = StoryRead.model_validate(story).model_dump(mode="json")
                encoded = json.dumps(payload, default=str)
                if encoded != last_payload:
                    yield f"event: story\ndata: {encoded}\n\n"
                    last_payload = encoded
                if story.status in _TERMINAL_STORY_STATUSES:
                    return
            await asyncio.sleep(2)

    return StreamingResponse(_events(), media_type="text/event-stream")


@router.post("/{story_id}/rewrite", response_model=StoryRead, status_code=status.HTTP_202_ACCEPTED)
async def rewrite_story_script(
    story_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> StoryORM:
    """Clone the story into a new revision and run an audit-driven rewrite on it."""
    story = await _get_story_for_user(
        db,
        story_id=story_id,
        current_user=current_user,
        include_owner=True,
    )
    if not story.script_data:
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail="Script is not available yet.",
        )
    if story.status not in _TERMINAL_STORY_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Story is currently {story.status}; wait for the current run to finish.",
        )

    clone = await _clone_story_for_revision(story, db, StoryStatus.SCRIPTING)
    _attach_story_owner(clone, getattr(story, "owner_email", None))
    background_tasks.add_task(_run_manual_script_rewrite, story_id=str(clone.id), source_story_id=str(story_id))
    return clone


@router.post("/{story_id}/regenerate", response_model=StoryRead, status_code=status.HTTP_202_ACCEPTED)
async def regenerate_story_script(
    story_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> StoryORM:
    """Clone the story into a new revision and re-run the full pipeline from analysis onward."""
    story = await _get_story_for_user(
        db,
        story_id=story_id,
        current_user=current_user,
        include_owner=True,
    )
    if not story.research_data:
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail="No research data available to regenerate from.",
        )
    if story.status not in _TERMINAL_STORY_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Story is currently {story.status}; wait for the current run to finish.",
        )

    clone = await _clone_story_for_revision(story, db, StoryStatus.ANALYSING)
    _attach_story_owner(clone, getattr(story, "owner_email", None))
    background_tasks.add_task(_run_script_regeneration, story_id=str(clone.id))
    return clone


@router.post("/{story_id}/implement-recommendations", response_model=StoryRead, status_code=status.HTTP_202_ACCEPTED)
async def implement_recommendations(
    story_id: uuid.UUID,
    payload: ImplementRecommendationsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> StoryORM:
    """Clone the story into a new revision and regenerate it around selected recommendations."""
    story = await _get_story_for_user(
        db,
        story_id=story_id,
        current_user=current_user,
        include_owner=True,
    )
    if not story.script_data:
        raise HTTPException(status_code=status.HTTP_425_TOO_EARLY, detail="No script to rewrite yet.")
    if story.status not in _TERMINAL_STORY_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Story is currently {story.status}; wait for the current run to finish.",
        )
    clone = await _clone_story_for_revision(
        story,
        db,
        StoryStatus.WRITING_STORYLINE,
        carry_outputs=False,
    )
    _attach_story_owner(clone, getattr(story, "owner_email", None))
    background_tasks.add_task(_run_implement_recommendations, story_id=str(clone.id), source_story_id=str(story_id), recommendations=payload.recommendations)
    return clone


@router.post("/{story_id}/select-angle", response_model=StoryRead, status_code=status.HTTP_202_ACCEPTED)
async def select_angle(
    story_id: uuid.UUID,
    payload: SelectAngleRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> StoryORM:
    """Persist the user's selected angle and resume the pipeline from Chapter Writer."""
    story = await _get_story_for_user(
        db,
        story_id=story_id,
        current_user=current_user,
        include_owner=True,
    )
    if story.status != StoryStatus.AWAITING_ANGLE_SELECTION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Story is currently {story.status}; angle selection only applies while awaiting_angle_selection.",
        )
    angle = payload.selected_angle.strip()
    # Allow the user to pick any of the generated angles, or (later, when inline
    # editing ships) submit an edited version — for now we just trust the value.
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(
            selected_angle=angle,
            status=StoryStatus.WRITING_STORYLINE,
            error_message=None,
        )
    )
    await db.commit()
    await db.refresh(story)
    _attach_story_owner(story, getattr(story, "owner_email", None))
    background_tasks.add_task(
        _run_pipeline_resume_after_angle_selection,
        story_id=str(story_id),
        selected_angle=angle,
    )
    return story


@router.post("/{story_id}/regenerate-angles", response_model=StoryRead, status_code=status.HTTP_202_ACCEPTED)
async def regenerate_angles(
    story_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> StoryORM:
    """Re-run the angle generator only, without re-running research/analysis."""
    story = await _get_story_for_user(
        db,
        story_id=story_id,
        current_user=current_user,
        include_owner=True,
    )
    if story.status != StoryStatus.AWAITING_ANGLE_SELECTION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Story is currently {story.status}; can only regenerate angles while awaiting selection.",
        )
    if not story.research_data or not story.analysis_data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Story is missing persisted research/analysis required to regenerate angles.",
        )
    # Clear current angles + selection so the UI shows a loading state until the
    # background task writes back the new set.
    await db.execute(
        update(StoryORM)
        .where(StoryORM.id == story_id)
        .values(angles_data=None, selected_angle=None)
    )
    await db.commit()
    await db.refresh(story)
    _attach_story_owner(story, getattr(story, "owner_email", None))
    background_tasks.add_task(_run_regenerate_angles, story_id=str(story_id))
    return story


@router.get("/{story_id}/sources")
async def get_research_sources(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """
    Return all research sources collected for this story.

    Sources include URLs, credibility ratings, relevance scores, and content previews.
    """
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user)
    if not story.research_data:
        return []

    raw_sources: list[dict] = story.research_data.get("sources", [])
    sorted_sources = sorted(
        raw_sources,
        key=lambda source: float(source.get("relevance_score") or 0.0),
        reverse=True,
    )
    return [
        {
            "title": s.get("title", ""),
            "source_id": s.get("source_id"),
            "url": s.get("url"),
            "source_type": s.get("source_type", ""),
            "credibility": s.get("credibility", "medium"),
            "relevance_score": s.get("relevance_score", 0.0),
            "author": s.get("author"),
            "published_at": s.get("published_at"),
            "content_preview": (s.get("content") or "")[:300],
        }
        for s in sorted_sources
        if s.get("title")
    ]


@router.post("/{story_id}/chat", response_model=ChatResponse)
async def chat_with_story(
    story_id: uuid.UUID,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> ChatResponse:
    """
    Chat with an AI research assistant scoped to this story.

    Supports:
    - Additional research questions and data-point suggestions
    - Script revision ideas
    - YouTube video recommendations (triggered by keywords: youtube, video, watch, footage)
    - Recommendation-based improvement advice
    """
    validate_user_input(payload.message, field="message")

    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user)

    fresh_context = ""
    if _should_fetch_fresh_research(payload.message):
        fresh_context = await _fresh_research_context(payload.message, story.topic)

    system_prompt = _build_chat_system_prompt(story, fresh_research_context=fresh_context)

    messages: list[Any] = [SystemMessage(content=system_prompt)]
    for msg in payload.history[-12:]:  # cap history at 12 messages to keep context manageable
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))
    messages.append(HumanMessage(content=payload.message))

    llm = ChatAnthropic(
        model=settings.claude_haiku_model,
        api_key=settings.anthropic_api_key,
        max_tokens=2000,
        temperature=0.3,
    )

    ai_response = await llm.ainvoke(messages)
    content = _normalise_chat_content(ai_response.content)

    # YouTube search when the user asks for videos
    youtube_results: list[dict[str, str]] = []
    msg_lower = payload.message.lower()
    if any(kw in msg_lower for kw in ["youtube", "video", "watch", "footage", "documentary"]):
        youtube_results = await _search_youtube(payload.message, story.topic)

    log.info(
        "chat.response_sent",
        story_id=str(story_id),
        yt_results=len(youtube_results),
        fresh_research=bool(fresh_context),
    )

    return ChatResponse(
        content=content,
        youtube_results=[YouTubeVideo(**v) for v in youtube_results],
    )


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> None:
    """Delete a story and all associated artefacts from the database."""
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user)
    await db.delete(story)
    await db.commit()
    log.info("stories.deleted", story_id=str(story_id))
