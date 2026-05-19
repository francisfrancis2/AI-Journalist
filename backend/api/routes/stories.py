"""
Stories API routes — CRUD + pipeline trigger + research chat endpoints.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.analyst import AnalystAgent
from backend.agents.benchmarker import BenchmarkAgent
from backend.agents.evaluator import EvaluatorAgent
from backend.agents.script_evaluator import ScriptEvaluatorAgent
from backend.agents.script_rewriter import ScriptRewriterAgent
from backend.agents.scriptwriter import ScriptwriterAgent
from backend.agents.storyline_creator import StorylineCreatorAgent
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
    ScriptAuditReport,
    StoryCreate,
    StoryListItem,
    StoryORM,
    StoryRead,
    StoryStatus,
)
from backend.models.user import UserORM
from backend.tools.anthropic_search import AnthropicSearchTool
from backend.tools.anthropic_deep_research import (
    AnthropicDeepResearchTool,
    DeepResearchCitation,
)
from backend.tools.news_api import NewsAPITool
from backend.tools.web_search import WebSearchTool

log = structlog.get_logger(__name__)
router = APIRouter()


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


class DeepResearchRequest(BaseModel):
    prompt: str = Field(..., min_length=4, max_length=2000)


class DeepResearchReport(BaseModel):
    story_id: uuid.UUID
    story_title: str
    prompt: str
    report_markdown: str
    citations: list[DeepResearchCitation] = Field(default_factory=list)
    model: str
    web_search_requests: int = 0
    generated_at: datetime


# ── Chat helpers ──────────────────────────────────────────────────────────────

_FRESH_RESEARCH_KEYWORDS = {
    "research",
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
    "gap",
    "gaps",
    "numbers",
    "news",
}


def _should_fetch_fresh_research(message: str) -> bool:
    lower = message.lower()
    return any(keyword in lower for keyword in _FRESH_RESEARCH_KEYWORDS)


async def _fresh_research_context(message: str, topic: str) -> str:
    """Run lightweight live search for story chat research requests."""
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
        sources.extend(result if isinstance(result, list) else [result])

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

    return "\n".join(lines)


def _build_deep_research_story_context(story: StoryORM) -> str:
    """Compact read-only context for Research Workspace deep research."""
    lines = [
        f"Title: {story.title}",
        f"Topic: {story.topic}",
        f"Tone: {story.tone}",
        f"Target duration: {story.target_duration_minutes} minutes",
    ]
    if story.target_audience:
        lines.append(f"Target audience: {story.target_audience}")
    if story.selected_angle:
        lines.append(f"Selected angle: {story.selected_angle}")

    if story.script_data:
        lines.append("\nCurrent script sections (read-only):")
        for section in story.script_data.get("sections", []):
            if not isinstance(section, dict):
                continue
            narration = str(section.get("narration") or "").strip()
            excerpt = narration[:1000] + ("..." if len(narration) > 1000 else "")
            source_ids = section.get("source_ids") or []
            if not isinstance(source_ids, list):
                source_ids = []
            lines.append(
                "\n".join(
                    [
                        f"- Act {section.get('section_number', '?')}: {section.get('title', 'Untitled')}",
                        f"  Source IDs: {', '.join(str(source_id) for source_id in source_ids) or 'None'}",
                        f"  Narration excerpt: {excerpt or 'Not available'}",
                    ]
                )
            )
    else:
        lines.append("\nCurrent script sections: Script not yet available.")

    if story.research_data:
        raw_sources = story.research_data.get("sources", [])
        if isinstance(raw_sources, list) and raw_sources:
            lines.append("\nSaved source pack highlights:")
            for source in raw_sources[:15]:
                if not isinstance(source, dict):
                    continue
                content = str(source.get("content") or "").strip()
                preview = content[:450] + ("..." if len(content) > 450 else "")
                lines.append(
                    "\n".join(
                        [
                            f"- {source.get('title', 'Untitled')}",
                            f"  URL: {source.get('url') or 'N/A'}",
                            f"  Source ID: {source.get('source_id') or 'N/A'}",
                            f"  Preview: {preview or 'No preview available'}",
                        ]
                    )
                )
    return "\n".join(lines)


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
    """Return a legacy persisted score only when the evaluator actually produced one."""
    if evaluation is None:
        return fallback
    return evaluation.overall_score


# ── Background pipeline runner ────────────────────────────────────────────────

_NODE_STATUS_MAP: dict[str, StoryStatus] = {
    "researcher": StoryStatus.RESEARCHING,
    "analyst": StoryStatus.ANALYSING,
    "storyline_creator": StoryStatus.WRITING_STORYLINE,
    "evaluator": StoryStatus.EVALUATING,
    "scriptwriter": StoryStatus.SCRIPTING,
    "script_rewriter": StoryStatus.SCRIPTING,
}

# Ordering used to guard against status regression when the graph is re-driven
# (e.g. resume after angle selection) — only advance forward, never backward.
_STATUS_PHASE_ORDER: dict[StoryStatus, int] = {
    StoryStatus.PENDING: 0,
    StoryStatus.RESEARCHING: 1,
    StoryStatus.ANALYSING: 2,
    StoryStatus.AWAITING_ANGLE_SELECTION: 3,
    StoryStatus.WRITING_STORYLINE: 4,
    StoryStatus.EVALUATING: 5,
    StoryStatus.SCRIPTING: 6,
    StoryStatus.COMPLETED: 7,
    StoryStatus.FAILED: 7,
}


def _status_for_completed_node(node_name: str, state: dict) -> Optional[StoryStatus]:
    """Decide what status the story should advance to after a node completes."""
    if node_name == "analyst" and state.get("generated_angles"):
        # If selected_angle is set (quality-gate restart path), don't pause —
        # the next node (storyline_creator) will move status forward instead.
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
            if new_status:
                await _advance_story_status(story_id, new_status)
                log.info("pipeline.node_complete", story_id=story_id, node=node_name, status=new_status)

    except Exception as exc:
        log.error("pipeline.failed", story_id=story_id, error=str(exc))
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(status=StoryStatus.FAILED, error_message=str(exc))
            )
            await db.commit()
        return

    # ── Paused at angle selection ─────────────────────────────────────────────
    # If we have angles but no selection, the graph ended after the analyst
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


def _hydrate_state_for_angle_resume(story: StoryORM, selected_angle: str) -> dict[str, Any]:
    """
    Rebuild graph state from the persisted story so the post-angle phase of the
    pipeline can resume. researcher_node and analyst_node skip themselves when
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
    """Re-run the merged analyst/angle step using persisted research."""
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
        agent = AnalystAgent()
        updates = await agent.run(state)
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
                state.update(await ScriptEvaluatorAgent().run(state))
            state.update(await ScriptRewriterAgent().run(state))
            state.update(await ScriptEvaluatorAgent().run(state))

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
                state.update(await AnalystAgent().run(state))

            state.update(await StorylineCreatorAgent().run(state))

            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(status=StoryStatus.EVALUATING)
            )
            await db.commit()
            eval_result, bench_result = await asyncio.gather(
                EvaluatorAgent().run(state),
                BenchmarkAgent().run(state),
                return_exceptions=True,
            )
            if not isinstance(eval_result, Exception):
                state.update(eval_result)
            if not isinstance(bench_result, Exception):
                state.update(bench_result)

            await db.execute(
                update(StoryORM)
                .where(StoryORM.id == uuid.UUID(story_id))
                .values(status=StoryStatus.SCRIPTING)
            )
            await db.commit()

            state.update(await ScriptwriterAgent().run(state))
            state.update(await ScriptEvaluatorAgent().run(state))

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
    """Re-run the full pipeline from Storyline Creator onward using updated research data."""
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
            state.update(await AnalystAgent().run(state))

            # Re-build storyline
            await db.execute(update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(status=StoryStatus.WRITING_STORYLINE))
            await db.commit()
            state.update(await StorylineCreatorAgent().run(state))

            # Evaluate
            await db.execute(update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(status=StoryStatus.EVALUATING))
            await db.commit()
            eval_result, bench_result = await asyncio.gather(
                EvaluatorAgent().run(state),
                BenchmarkAgent().run(state),
                return_exceptions=True,
            )
            if not isinstance(eval_result, Exception):
                state.update(eval_result)
            if not isinstance(bench_result, Exception):
                state.update(bench_result)

            # Write script
            await db.execute(update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(status=StoryStatus.SCRIPTING))
            await db.commit()
            state.update(await ScriptwriterAgent().run(state))
            state.update(await ScriptEvaluatorAgent().run(state))

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
                if story.status in {StoryStatus.COMPLETED, StoryStatus.FAILED}:
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
    if story.status not in {StoryStatus.COMPLETED, StoryStatus.FAILED}:
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
    if story.status not in {StoryStatus.COMPLETED, StoryStatus.FAILED}:
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
    if story.status not in {StoryStatus.COMPLETED, StoryStatus.FAILED}:
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
    """Persist the user's selected angle and resume the pipeline from storyline_creator."""
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


@router.post("/{story_id}/deep-research", response_model=DeepResearchReport)
async def run_deep_research_report(
    story_id: uuid.UUID,
    payload: DeepResearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> DeepResearchReport:
    """
    Generate a read-only Anthropic deep research report for the selected story.

    This endpoint intentionally does not update the story, regenerate analysis,
    or rewrite the existing script.
    """
    validate_user_input(payload.prompt, field="prompt")
    story = await _get_story_for_user(db, story_id=story_id, current_user=current_user)

    try:
        result = await AnthropicDeepResearchTool().run(
            prompt=payload.prompt,
            story_context=_build_deep_research_story_context(story),
        )
    except Exception as exc:
        log.error("deep_research.failed", story_id=str(story_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Anthropic deep research could not complete. Please try again.",
        ) from exc

    log.info(
        "deep_research.complete",
        story_id=str(story_id),
        citations=len(result.citations),
        web_search_requests=result.web_search_requests,
    )
    return DeepResearchReport(
        story_id=story.id,
        story_title=story.title,
        prompt=payload.prompt,
        report_markdown=result.report_markdown,
        citations=result.citations,
        model=result.model,
        web_search_requests=result.web_search_requests,
        generated_at=datetime.now(timezone.utc),
    )


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
