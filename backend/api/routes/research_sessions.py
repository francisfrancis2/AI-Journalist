"""
Research Sessions API routes — standalone Research Hub.

Each session is a chat-style canvas owned by a single user. The first prompt
generates an initial consolidated report. Every follow-up re-synthesizes the
full report (integrating new findings, honoring removal/extension requests).
Citations are merged across turns (dedupe by URL).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.security import validate_user_input
from backend.db.database import AsyncSessionLocal, get_db
from backend.models.research_session import (
    ResearchSessionCitation,
    ResearchSessionCreate,
    ResearchSessionListItem,
    ResearchSessionORM,
    ResearchSessionRead,
    ResearchSessionStatus,
    ResearchSessionTurn,
    ResearchSessionTurnCreate,
)
from backend.models.user import UserORM
from backend.tools.anthropic_deep_research import (
    DeepResearchCitation,
    _merge_citations,
)

log = structlog.get_logger(__name__)
router = APIRouter()

# Lazily-instantiated shared Research Agent — the unified research engine
# (all tools + always-on Anthropic deep research) that backs the Research Tab.
_research_agent = None


def _get_research_agent():
    global _research_agent
    if _research_agent is None:
        from backend.agents.research import ResearchAgent

        _research_agent = ResearchAgent()
    return _research_agent


# ── Helpers ───────────────────────────────────────────────────────────────────


def _derive_title(prompt: str, max_len: int = 80) -> str:
    cleaned = " ".join(prompt.strip().split())
    if not cleaned:
        return "Untitled research"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def _citations_to_orm(citations: list[DeepResearchCitation]) -> list[dict]:
    return [citation.model_dump(mode="json") for citation in citations]


def _orm_to_citations(raw: Optional[list]) -> list[DeepResearchCitation]:
    if not raw:
        return []
    parsed: list[DeepResearchCitation] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                parsed.append(DeepResearchCitation(**item))
            except Exception:
                continue
    return parsed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _turn_record(
    prompt: str,
    *,
    status: ResearchSessionStatus = ResearchSessionStatus.COMPLETED,
    error_message: str | None = None,
    report_markdown: str = "",
    citations: list[DeepResearchCitation] | None = None,
    web_search_requests: int = 0,
) -> dict:
    now = _utc_now().isoformat()
    return {
        "prompt": prompt,
        "created_at": now,
        "status": status.value,
        "completed_at": now if status in {ResearchSessionStatus.COMPLETED, ResearchSessionStatus.FAILED} else None,
        "error_message": error_message,
        "report_markdown": report_markdown,
        "citations": _citations_to_orm(citations or []),
        "web_search_requests": web_search_requests,
    }


def _mark_latest_turn(
    turns: Optional[list],
    *,
    status: ResearchSessionStatus,
    error_message: str | None = None,
    report_markdown: str | None = None,
    citations: list[DeepResearchCitation] | None = None,
    web_search_requests: int | None = None,
) -> list:
    cleaned = [item for item in (turns or []) if isinstance(item, dict)]
    if not cleaned:
        return cleaned
    latest = dict(cleaned[-1])
    latest["status"] = status.value
    latest["completed_at"] = _utc_now().isoformat()
    latest["error_message"] = error_message
    if report_markdown is not None:
        latest["report_markdown"] = report_markdown
    if citations is not None:
        latest["citations"] = _citations_to_orm(citations)
    if web_search_requests is not None:
        latest["web_search_requests"] = web_search_requests
    return [*cleaned[:-1], latest]


def _to_read_model(session: ResearchSessionORM, owner_email: Optional[str] = None) -> ResearchSessionRead:
    return ResearchSessionRead(
        owner_email=owner_email,
        id=session.id,
        title=session.title,
        report_markdown=session.report_markdown,
        citations=[
            ResearchSessionCitation(**citation)
            for citation in (session.citations or [])
            if isinstance(citation, dict)
        ],
        turns=[
            ResearchSessionTurn(**turn)
            for turn in (session.turns or [])
            if isinstance(turn, dict)
        ],
        model=session.model,
        web_search_requests=session.web_search_requests or 0,
        status=session.status,
        active_operation=session.active_operation,
        pending_prompt=session.pending_prompt,
        error_message=session.error_message,
        operation_started_at=session.operation_started_at,
        operation_completed_at=session.operation_completed_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


async def _get_session_for_user(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    current_user: UserORM,
) -> ResearchSessionORM:
    result = await db.execute(
        select(ResearchSessionORM).where(ResearchSessionORM.id == session_id)
    )
    session = result.scalar_one_or_none()
    # Admins may read/operate on any user's session; everyone else is scoped to
    # their own. Mirrors the story access model (_apply_story_access_scope).
    if session is None or (session.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Research session not found",
        )
    return session


async def _owner_email(db: AsyncSession, user_id: uuid.UUID) -> Optional[str]:
    result = await db.execute(select(UserORM.email).where(UserORM.id == user_id))
    return result.scalar_one_or_none()


async def _run_initial_research_session(session_id: uuid.UUID) -> None:
    """Complete the first research report for an already-created session row."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ResearchSessionORM).where(ResearchSessionORM.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return
        prompt = (session.pending_prompt or "").strip()
        if not prompt:
            session.status = ResearchSessionStatus.FAILED.value
            session.error_message = "No research prompt was available."
            session.active_operation = None
            session.pending_prompt = None
            session.operation_completed_at = _utc_now()
            session.turns = _mark_latest_turn(
                session.turns,
                status=ResearchSessionStatus.FAILED,
                error_message=session.error_message,
            )
            await db.commit()
            return

    try:
        result = await _get_research_agent().run_report(prompt=prompt)
    except Exception as exc:
        log.error("research_session.initial.failed", session_id=str(session_id), error=str(exc))
        async with AsyncSessionLocal() as db:
            session = await db.get(ResearchSessionORM, session_id)
            if session is None:
                return
            session.status = ResearchSessionStatus.FAILED.value
            session.error_message = "Research could not complete. Please try again."
            session.active_operation = None
            session.pending_prompt = None
            session.operation_completed_at = _utc_now()
            session.turns = _mark_latest_turn(
                session.turns,
                status=ResearchSessionStatus.FAILED,
                error_message=session.error_message,
            )
            await db.commit()
        return

    async with AsyncSessionLocal() as db:
        session = await db.get(ResearchSessionORM, session_id)
        if session is None:
            return
        session.report_markdown = result.report_markdown
        session.citations = _citations_to_orm(result.citations)
        session.turns = _mark_latest_turn(
            session.turns,
            status=ResearchSessionStatus.COMPLETED,
            report_markdown=result.report_markdown,
            citations=result.citations,
            web_search_requests=result.web_search_requests,
        )
        session.model = result.model
        session.web_search_requests = result.web_search_requests
        session.status = ResearchSessionStatus.COMPLETED.value
        session.active_operation = None
        session.pending_prompt = None
        session.error_message = None
        session.operation_completed_at = _utc_now()
        await db.commit()
        log.info(
            "research_session.created",
            session_id=str(session_id),
            user_id=str(session.user_id),
            citations=len(result.citations),
            web_search_requests=result.web_search_requests,
        )


async def _run_research_session_turn(session_id: uuid.UUID) -> None:
    """Complete a follow-up turn for an existing research session."""
    async with AsyncSessionLocal() as db:
        session = await db.get(ResearchSessionORM, session_id)
        if session is None:
            return
        prompt = (session.pending_prompt or "").strip()
        existing_report = session.report_markdown
        existing_citations = _orm_to_citations(session.citations)

    try:
        result = await _get_research_agent().run_report(
            prompt=prompt,
            existing_report=existing_report,
            existing_citations=existing_citations,
        )
    except Exception as exc:
        log.error("research_session.turn.failed", session_id=str(session_id), error=str(exc))
        async with AsyncSessionLocal() as db:
            session = await db.get(ResearchSessionORM, session_id)
            if session is None:
                return
            session.status = ResearchSessionStatus.FAILED.value
            session.error_message = "Follow-up research could not complete. Please try again."
            session.active_operation = None
            session.pending_prompt = None
            session.operation_completed_at = _utc_now()
            session.turns = _mark_latest_turn(
                session.turns,
                status=ResearchSessionStatus.FAILED,
                error_message=session.error_message,
            )
            await db.commit()
        return

    merged_citations = _merge_citations(existing_citations, result.citations)
    async with AsyncSessionLocal() as db:
        session = await db.get(ResearchSessionORM, session_id)
        if session is None:
            return
        session.report_markdown = result.report_markdown
        session.citations = _citations_to_orm(merged_citations)
        session.turns = _mark_latest_turn(
            session.turns,
            status=ResearchSessionStatus.COMPLETED,
            report_markdown=result.report_markdown,
            citations=result.citations,
            web_search_requests=result.web_search_requests,
        )
        session.model = result.model
        session.web_search_requests = (session.web_search_requests or 0) + result.web_search_requests
        session.status = ResearchSessionStatus.COMPLETED.value
        session.active_operation = None
        session.pending_prompt = None
        session.error_message = None
        session.operation_completed_at = _utc_now()
        await db.commit()
        log.info(
            "research_session.turn.completed",
            session_id=str(session_id),
            user_id=str(session.user_id),
            added_citations=len(result.citations),
            merged_citations=len(merged_citations),
            web_search_requests=result.web_search_requests,
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/sessions", response_model=list[ResearchSessionListItem])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> list[ResearchSessionListItem]:
    # Admins see every user's research history (attributed by owner email);
    # everyone else sees only their own sessions.
    stmt = (
        select(ResearchSessionORM, UserORM.email)
        .outerjoin(UserORM, ResearchSessionORM.user_id == UserORM.id)
        .order_by(ResearchSessionORM.updated_at.desc())
    )
    if not current_user.is_admin:
        stmt = stmt.where(ResearchSessionORM.user_id == current_user.id)
    result = await db.execute(stmt)
    return [
        ResearchSessionListItem(
            id=session.id,
            title=session.title,
            status=session.status,
            active_operation=session.active_operation,
            pending_prompt=session.pending_prompt,
            error_message=session.error_message,
            operation_started_at=session.operation_started_at,
            updated_at=session.updated_at,
            created_at=session.created_at,
            owner_email=owner_email if current_user.is_admin else None,
        )
        for session, owner_email in result.all()
    ]


@router.post("/sessions", response_model=ResearchSessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: ResearchSessionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> ResearchSessionRead:
    validate_user_input(payload.prompt, field="prompt")
    prompt = payload.prompt.strip()

    session = ResearchSessionORM(
        user_id=current_user.id,
        title=_derive_title(prompt),
        report_markdown="",
        citations=[],
        turns=[_turn_record(prompt, status=ResearchSessionStatus.RUNNING)],
        status=ResearchSessionStatus.RUNNING.value,
        active_operation="initial",
        pending_prompt=prompt,
        operation_started_at=_utc_now(),
        operation_completed_at=None,
        error_message=None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    background_tasks.add_task(_run_initial_research_session, session_id=session.id)
    return _to_read_model(session)


@router.get("/sessions/{session_id}", response_model=ResearchSessionRead)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> ResearchSessionRead:
    session = await _get_session_for_user(db, session_id=session_id, current_user=current_user)
    owner_email = await _owner_email(db, session.user_id) if current_user.is_admin else None
    return _to_read_model(session, owner_email=owner_email)


@router.post("/sessions/{session_id}/turns", response_model=ResearchSessionRead)
async def add_turn(
    session_id: uuid.UUID,
    payload: ResearchSessionTurnCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> ResearchSessionRead:
    validate_user_input(payload.prompt, field="prompt")
    prompt = payload.prompt.strip()
    session = await _get_session_for_user(db, session_id=session_id, current_user=current_user)
    if session.status == ResearchSessionStatus.RUNNING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A research request is already running for this session.",
        )

    session.status = ResearchSessionStatus.RUNNING.value
    session.active_operation = "turn"
    session.pending_prompt = prompt
    session.error_message = None
    session.operation_started_at = _utc_now()
    session.operation_completed_at = None
    session.turns = [*(session.turns or []), _turn_record(prompt, status=ResearchSessionStatus.RUNNING)]
    await db.commit()
    await db.refresh(session)
    background_tasks.add_task(_run_research_session_turn, session_id=session.id)
    return _to_read_model(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> None:
    session = await _get_session_for_user(db, session_id=session_id, current_user=current_user)
    await db.execute(
        delete(ResearchSessionORM).where(ResearchSessionORM.id == session.id)
    )
    await db.commit()
    log.info(
        "research_session.deleted",
        session_id=str(session_id),
        user_id=str(current_user.id),
    )
