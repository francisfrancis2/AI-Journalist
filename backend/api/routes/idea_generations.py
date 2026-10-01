"""Idea Generator V2 API routes."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.deps import get_current_user
from backend.config import settings
from backend.db.database import AsyncSessionLocal, get_db
from backend.models.idea_generation import (
    CoverageLevel,
    GeneratedIdeaORM,
    GeneratedIdeaRead,
    IdeaFormat,
    IdeaGenerationCreate,
    IdeaGenerationRunListItem,
    IdeaGenerationRunORM,
    IdeaGenerationRunRead,
    IdeaHandoffPreview,
    IdeaRunStatus,
    IdeaSignalORM,
    IdeaSignalRead,
    IdeaSourceORM,
    IdeaSourceRead,
    IdeaStateUpdate,
)
from backend.models.user import UserORM

log = structlog.get_logger(__name__)
router = APIRouter()
_idea_agent = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_agent():
    global _idea_agent
    if _idea_agent is None:
        from backend.agents.idea_generator import IdeaGeneratorAgent

        _idea_agent = IdeaGeneratorAgent()
    return _idea_agent


def _request_hash(payload: IdeaGenerationCreate) -> str:
    body = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def _source_read(source: IdeaSourceORM) -> IdeaSourceRead:
    return IdeaSourceRead(
        id=source.id,
        title=source.title,
        url=source.url,
        domain=source.domain,
        publisher=source.publisher,
        published_at=source.published_at,
        excerpt=source.excerpt,
        source_type=source.source_type,
        credibility=source.credibility,
        is_uae_relevant=source.is_uae_relevant,
        is_primary=source.is_primary,
    )


def _signal_read(signal: IdeaSignalORM) -> IdeaSignalRead:
    return IdeaSignalRead(
        id=signal.id,
        provider=signal.provider,
        signal_type=signal.signal_type,
        topic=signal.topic,
        query=signal.query,
        geography=signal.geography,
        geography_meaning=signal.geography_meaning,
        metric=signal.metric,
        values=signal.values or {},
        reliability=signal.reliability,
    )


def _idea_read(idea: GeneratedIdeaORM) -> GeneratedIdeaRead:
    return GeneratedIdeaRead(
        id=idea.id,
        rank=idea.rank,
        format=idea.format,
        sector=idea.sector,
        title=idea.title,
        premise=idea.premise,
        why_now=idea.why_now,
        uae_relevance=idea.uae_relevance,
        central_tension=idea.central_tension,
        target_audience=idea.target_audience,
        business_significance=idea.business_significance,
        format_details=idea.format_details or {},
        score_breakdown=idea.score_breakdown or {},
        score=idea.score,
        strength=idea.strength,
        confidence=idea.confidence,
        coverage=idea.coverage or {},
        verification_gaps=idea.verification_gaps or [],
        state=idea.state,
        story_id=idea.story_id,
        research_session_id=idea.research_session_id,
        sources=[_source_read(source) for source in idea.sources],
        signals=[_signal_read(signal) for signal in idea.signals],
    )


def _run_read(run: IdeaGenerationRunORM) -> IdeaGenerationRunRead:
    return IdeaGenerationRunRead(
        id=run.id,
        format=run.format,
        geography=run.geography,
        trend_window_days=run.trend_window_days,
        status=run.status,
        stage=run.stage,
        stage_progress=run.stage_progress,
        coverage_level=run.coverage_level,
        coverage_reasons=run.coverage_reasons or [],
        provider_statuses=run.provider_statuses or {},
        candidate_metrics=run.candidate_metrics or {},
        usage_metrics=run.usage_metrics or {},
        previous_run_id=run.previous_run_id,
        error_code=run.error_code,
        error_message=run.error_message,
        ideas=[_idea_read(idea) for idea in run.ideas],
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
    )


async def _load_run(db: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID) -> IdeaGenerationRunORM:
    result = await db.execute(
        select(IdeaGenerationRunORM)
        .options(
            selectinload(IdeaGenerationRunORM.ideas).selectinload(GeneratedIdeaORM.sources),
            selectinload(IdeaGenerationRunORM.ideas).selectinload(GeneratedIdeaORM.signals),
        )
        .where(IdeaGenerationRunORM.id == run_id, IdeaGenerationRunORM.user_id == user_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea generation run not found")
    return run


async def _load_idea(db: AsyncSession, idea_id: uuid.UUID, user_id: uuid.UUID) -> GeneratedIdeaORM:
    result = await db.execute(
        select(GeneratedIdeaORM)
        .join(IdeaGenerationRunORM)
        .options(selectinload(GeneratedIdeaORM.sources), selectinload(GeneratedIdeaORM.signals))
        .where(GeneratedIdeaORM.id == idea_id, IdeaGenerationRunORM.user_id == user_id)
    )
    idea = result.scalar_one_or_none()
    if idea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found")
    return idea


async def _run_generation(run_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        run = await db.get(IdeaGenerationRunORM, run_id)
        if run is None:
            return
        run.status = IdeaRunStatus.RUNNING.value
        run.stage = "researching_uae_business_trends"
        run.stage_progress = 15
        run.started_at = _utc_now()
        await db.commit()
        idea_format = IdeaFormat(run.format)

    try:
        result = await _get_agent().generate(idea_format)
    except Exception as exc:
        code = "insufficient_evidence" if str(exc) == "insufficient_evidence" else "generation_failed"
        log.error("idea_generator.failed", run_id=str(run_id), code=code, error=str(exc)[:300])
        async with AsyncSessionLocal() as db:
            run = await db.get(IdeaGenerationRunORM, run_id)
            if run is None:
                return
            run.status = IdeaRunStatus.FAILED.value
            run.stage = "failed"
            run.stage_progress = 100
            run.error_code = code
            run.error_message = (
                "Not enough independently verified evidence was available to produce five ideas."
                if code == "insufficient_evidence"
                else "Idea generation could not complete. Please retry."
            )
            run.completed_at = _utc_now()
            await db.commit()
        return

    async with AsyncSessionLocal() as db:
        run = await db.get(IdeaGenerationRunORM, run_id)
        if run is None:
            return
        run.stage = "ranking_verified_ideas"
        run.stage_progress = 85
        source_rows: dict[uuid.UUID, IdeaSourceORM] = {}
        for source in result.sources:
            row = IdeaSourceORM(
                id=source.id,
                run_id=run.id,
                url=source.url,
                domain=source.domain,
                title=source.title,
                publisher=source.publisher,
                published_at=source.published_at,
                excerpt=source.excerpt,
                source_type=source.source_type,
                credibility=source.credibility,
                is_uae_relevant=source.is_uae_relevant,
                is_primary=source.is_primary,
                content_hash=source.content_hash,
                raw_metadata=source.raw_metadata,
            )
            source_rows[source.id] = row
            db.add(row)
        signal_rows: dict[uuid.UUID, IdeaSignalORM] = {}
        for signal in result.signals:
            row = IdeaSignalORM(
                id=signal.id,
                run_id=run.id,
                provider=signal.provider,
                signal_type=signal.signal_type,
                topic=signal.topic,
                query=signal.query,
                geography=signal.geography,
                geography_meaning=signal.geography_meaning,
                observed_at=signal.observed_at,
                window_days=signal.window_days,
                metric=signal.metric,
                values=signal.values,
                source_url=signal.source_url,
                domain=signal.domain,
                reliability=signal.reliability,
                is_cached=signal.is_cached,
                raw_reference=signal.raw_reference,
            )
            signal_rows[signal.id] = row
            db.add(row)
        for scored in result.ideas:
            candidate = scored.candidate
            idea = GeneratedIdeaORM(
                run_id=run.id,
                rank=scored.rank,
                format=run.format,
                sector=candidate.sector,
                title=candidate.title,
                premise=candidate.premise,
                why_now=candidate.why_now,
                uae_relevance=candidate.uae_relevance,
                central_tension=candidate.central_tension,
                target_audience=candidate.target_audience,
                business_significance=candidate.business_significance,
                format_details=candidate.format_details,
                score_breakdown=scored.score_breakdown,
                score=scored.score,
                strength=scored.strength,
                confidence=scored.confidence,
                coverage={"level": "partial", "reasons": result.coverage_reasons},
                verification_gaps=candidate.verification_gaps,
                sources=[source_rows[item] for item in scored.source_ids if item in source_rows],
                signals=[signal_rows[item] for item in scored.signal_ids if item in signal_rows],
            )
            db.add(idea)
        run.provider_statuses = result.provider_statuses
        run.coverage_reasons = result.coverage_reasons
        run.coverage_level = CoverageLevel.PARTIAL.value
        run.candidate_metrics = result.candidate_metrics
        run.usage_metrics = result.usage_metrics
        run.status = IdeaRunStatus.COMPLETED.value
        run.stage = "completed"
        run.stage_progress = 100
        run.error_code = None
        run.error_message = None
        run.completed_at = _utc_now()
        await db.commit()


async def _create_run(
    *,
    payload: IdeaGenerationCreate,
    idempotency_key: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
    user_id: uuid.UUID,
) -> IdeaGenerationRunORM:
    digest = _request_hash(payload)
    existing_result = await db.execute(
        select(IdeaGenerationRunORM).where(
            IdeaGenerationRunORM.user_id == user_id,
            IdeaGenerationRunORM.idempotency_key == idempotency_key,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        if existing.request_hash != digest:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different request")
        return await _load_run(db, existing.id, user_id)

    active_result = await db.execute(
        select(IdeaGenerationRunORM)
        .where(
            IdeaGenerationRunORM.user_id == user_id,
            IdeaGenerationRunORM.status.in_([IdeaRunStatus.QUEUED.value, IdeaRunStatus.RUNNING.value]),
        )
        .order_by(IdeaGenerationRunORM.created_at.desc())
        .limit(1)
    )
    active = active_result.scalar_one_or_none()
    if active:
        return await _load_run(db, active.id, user_id)

    if payload.previous_run_id:
        await _load_run(db, payload.previous_run_id, user_id)
    run = IdeaGenerationRunORM(
        user_id=user_id,
        idempotency_key=idempotency_key,
        request_hash=digest,
        format=payload.format.value,
        previous_run_id=payload.previous_run_id,
        status=IdeaRunStatus.QUEUED.value,
        stage="queued",
        stage_progress=0,
        coverage_level=CoverageLevel.PARTIAL.value,
        coverage_reasons=["google_trends_not_configured"],
        provider_statuses={
            "google_trends": {
                "status": "not_configured",
                "detail": "Google Trends is intentionally not implemented in V2.",
                "evidence_count": 0,
            }
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    background_tasks.add_task(_run_generation, run.id)
    return await _load_run(db, run.id, user_id)


@router.post("", response_model=IdeaGenerationRunRead, status_code=status.HTTP_202_ACCEPTED)
async def create_idea_generation(
    payload: IdeaGenerationCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> IdeaGenerationRunRead:
    if not settings.enable_idea_generator:
        raise HTTPException(status_code=503, detail="Idea Generator is disabled")
    key = (idempotency_key or str(uuid.uuid4())).strip()
    if len(key) > 128:
        raise HTTPException(status_code=422, detail="Idempotency-Key cannot exceed 128 characters")
    run = await _create_run(
        payload=payload,
        idempotency_key=key,
        background_tasks=background_tasks,
        db=db,
        user_id=current_user.id,
    )
    return _run_read(run)


@router.get("", response_model=list[IdeaGenerationRunListItem])
async def list_idea_generations(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> list[IdeaGenerationRunListItem]:
    result = await db.execute(
        select(IdeaGenerationRunORM)
        .options(selectinload(IdeaGenerationRunORM.ideas))
        .where(IdeaGenerationRunORM.user_id == current_user.id)
        .order_by(IdeaGenerationRunORM.created_at.desc())
        .limit(limit)
    )
    return [
        IdeaGenerationRunListItem(
            id=run.id,
            format=run.format,
            status=run.status,
            coverage_level=run.coverage_level,
            stage=run.stage,
            idea_count=len(run.ideas),
            created_at=run.created_at,
            updated_at=run.updated_at,
            error_message=run.error_message,
        )
        for run in result.scalars().all()
    ]


@router.get("/{run_id}", response_model=IdeaGenerationRunRead)
async def get_idea_generation(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeaGenerationRunRead:
    return _run_read(await _load_run(db, run_id, current_user.id))


@router.post("/{run_id}/retry", response_model=IdeaGenerationRunRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_idea_generation(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeaGenerationRunRead:
    prior = await _load_run(db, run_id, current_user.id)
    if prior.status not in {IdeaRunStatus.FAILED.value, IdeaRunStatus.COMPLETED.value}:
        raise HTTPException(status_code=409, detail="The current run is still active")
    payload = IdeaGenerationCreate(format=IdeaFormat(prior.format), previous_run_id=prior.id)
    run = await _create_run(
        payload=payload,
        idempotency_key=str(uuid.uuid4()),
        background_tasks=background_tasks,
        db=db,
        user_id=current_user.id,
    )
    return _run_read(run)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_idea_generation(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> None:
    run = await _load_run(db, run_id, current_user.id)
    if run.status in {IdeaRunStatus.QUEUED.value, IdeaRunStatus.RUNNING.value}:
        raise HTTPException(status_code=409, detail="An active run cannot be deleted")
    await db.execute(delete(IdeaGenerationRunORM).where(IdeaGenerationRunORM.id == run.id))
    await db.commit()


@router.post("/ideas/{idea_id}/state", response_model=GeneratedIdeaRead)
async def update_idea_state(
    idea_id: uuid.UUID,
    payload: IdeaStateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> GeneratedIdeaRead:
    idea = await _load_idea(db, idea_id, current_user.id)
    idea.state = payload.state.value
    await db.commit()
    await db.refresh(idea)
    return _idea_read(idea)


@router.get("/ideas/{idea_id}/handoff", response_model=IdeaHandoffPreview)
async def idea_handoff_preview(
    idea_id: uuid.UUID,
    target: Literal["story", "research"] = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeaHandoffPreview:
    idea = await _load_idea(db, idea_id, current_user.id)
    allowed = target == "research" or idea.format == IdeaFormat.DOCUMENTARY.value
    prompt = (
        f"{idea.title}\n\nPremise: {idea.premise}\nWhy now: {idea.why_now}\n"
        f"UAE relevance: {idea.uae_relevance}\nCentral tension: {idea.central_tension}"
    )
    return IdeaHandoffPreview(
        idea_id=idea.id,
        target=target,
        allowed=allowed,
        prompt=prompt,
        title=idea.title,
        inherited_source_count=len(idea.sources),
        message=(
            "Review and edit this brief, then confirm to create a seeded workspace. No research starts from this preview."
            if allowed
            else "Expert Interview ideas can be opened in Research, but cannot be developed as documentary Stories."
        ),
    )
