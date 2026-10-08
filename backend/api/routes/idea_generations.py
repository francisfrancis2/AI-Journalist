"""Idea Generator V2 API routes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.deps import get_current_user
from backend.config import settings
from backend.services.cost_ledger import BudgetExceeded
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
_WORKER_ID = uuid.uuid4().hex
_GENERATION_TASKS: dict[uuid.UUID, asyncio.Task] = {}
_INTERRUPTED_MESSAGE = (
    "Idea generation was interrupted more than once before completing. "
    "Please retry the run."
)


class IdeaGenerationLeaseLost(RuntimeError):
    """Raised inside a worker that no longer owns its Idea run."""


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
        started_at=run.started_at,
        completed_at=run.completed_at,
        estimated_total_seconds=settings.idea_generator_total_timeout_seconds,
        deadline_at=(
            run.started_at + timedelta(seconds=settings.idea_generator_total_timeout_seconds)
            if run.started_at is not None
            else None
        ),
    )


async def _load_run(
    db: AsyncSession,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    allow_any_owner: bool = False,
) -> IdeaGenerationRunORM:
    """Load a run with its ideas, sources and signals.

    ``allow_any_owner`` is for admin reads only. Admins see every user's idea
    history in the listing, so opening one has to work too. Mutations -- retry
    and delete -- stay owner-scoped whoever is asking.
    """
    stmt = (
        select(IdeaGenerationRunORM)
        .options(
            selectinload(IdeaGenerationRunORM.ideas).selectinload(GeneratedIdeaORM.sources),
            selectinload(IdeaGenerationRunORM.ideas).selectinload(GeneratedIdeaORM.signals),
        )
        .where(IdeaGenerationRunORM.id == run_id)
    )
    if not allow_any_owner:
        stmt = stmt.where(IdeaGenerationRunORM.user_id == user_id)
    result = await db.execute(stmt)
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


def _lease_expiry(now: datetime) -> datetime:
    return now + timedelta(seconds=settings.idea_generator_worker_lease_seconds)


async def _claim_generation_run(
    run_id: uuid.UUID,
) -> tuple[IdeaFormat, int, datetime] | None:
    """Atomically claim a queued run or an expired lease.

    The conditional UPDATE is the cross-process lock. If V1 and V2 discover the
    same recoverable row, only one receives it from RETURNING; the other exits
    without making provider calls.
    """
    now = _utc_now()
    expired = or_(
        IdeaGenerationRunORM.lease_expires_at.is_(None),
        IdeaGenerationRunORM.lease_expires_at <= now,
    )
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(IdeaGenerationRunORM)
            .where(
                IdeaGenerationRunORM.id == run_id,
                IdeaGenerationRunORM.attempt_count < settings.idea_generator_max_worker_attempts,
                or_(
                    IdeaGenerationRunORM.status == IdeaRunStatus.QUEUED.value,
                    and_(
                        IdeaGenerationRunORM.status == IdeaRunStatus.RUNNING.value,
                        expired,
                    ),
                ),
            )
            .values(
                status=IdeaRunStatus.RUNNING.value,
                stage="researching_uae_business_trends",
                stage_progress=15,
                worker_id=_WORKER_ID,
                heartbeat_at=now,
                lease_expires_at=_lease_expiry(now),
                attempt_count=IdeaGenerationRunORM.attempt_count + 1,
                # Preserve the original wall-clock deadline on recovery.
                started_at=func.coalesce(IdeaGenerationRunORM.started_at, now),
                completed_at=None,
                error_code=None,
                error_message=None,
                updated_at=now,
            )
            .returning(
                IdeaGenerationRunORM.format,
                IdeaGenerationRunORM.attempt_count,
                IdeaGenerationRunORM.started_at,
            )
        )
        claimed = result.first()
        await db.commit()
    if claimed is None:
        return None
    started_at = claimed[2]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return IdeaFormat(claimed[0]), int(claimed[1]), started_at


async def _renew_generation_lease(run_id: uuid.UUID, worker_id: str) -> bool:
    now = _utc_now()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(IdeaGenerationRunORM)
            .where(
                IdeaGenerationRunORM.id == run_id,
                IdeaGenerationRunORM.status == IdeaRunStatus.RUNNING.value,
                IdeaGenerationRunORM.worker_id == worker_id,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=_lease_expiry(now),
                updated_at=now,
            )
        )
        await db.commit()
        return (result.rowcount or 0) == 1


async def _set_generation_stage(
    run_id: uuid.UUID,
    worker_id: str,
    stage: str,
    progress: int,
) -> bool:
    now = _utc_now()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(IdeaGenerationRunORM)
            .where(
                IdeaGenerationRunORM.id == run_id,
                IdeaGenerationRunORM.status == IdeaRunStatus.RUNNING.value,
                IdeaGenerationRunORM.worker_id == worker_id,
            )
            .values(
                stage=stage,
                stage_progress=progress,
                heartbeat_at=now,
                lease_expires_at=_lease_expiry(now),
                updated_at=now,
            )
        )
        await db.commit()
        return (result.rowcount or 0) == 1


async def _persist_generation_result(run_id: uuid.UUID, worker_id: str, result) -> bool:
    async with AsyncSessionLocal() as db:
        owned_run = await db.execute(
            select(IdeaGenerationRunORM)
            .where(
                IdeaGenerationRunORM.id == run_id,
                IdeaGenerationRunORM.status == IdeaRunStatus.RUNNING.value,
                IdeaGenerationRunORM.worker_id == worker_id,
            )
            .execution_options(populate_existing=True)
        )
        run = owned_run.scalar_one_or_none()
        if run is None:
            return False
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
        run.heartbeat_at = run.completed_at
        run.lease_expires_at = None
        run.worker_id = None
        await db.commit()
        return True


async def _mark_generation_failed(
    run_id: uuid.UUID,
    worker_id: str,
    *,
    code: str,
    detail: str,
) -> bool:
    # Every code the pipeline can emit needs an entry here. Four of them had no
    # message and fell through to a generic "could not complete. Please retry.",
    # which is what a user sees for the two most likely production failures --
    # a run interrupted by a deploy, and the spend ceiling being reached. The
    # generic line hid the cause and made the failure undiagnosable from the UI.
    messages = {
        "insufficient_evidence": "Not enough independently verified evidence was available to produce ideas.",
        "research_timed_out": "Research exceeded its time budget. Please retry the run.",
        "synthesis_timed_out": "Idea synthesis exceeded its time budget. Please retry the run.",
        "repair_timed_out": "Idea validation could not finish in time. Please retry the run.",
        "generation_timed_out": "Idea generation reached the five-minute limit. Please retry the run.",
        "interrupted": (
            "The server restarted while this run was in progress and it could not "
            "resume. Nothing was charged for the unfinished work. Please retry."
        ),
        "idea_generation_lease_lost": (
            "The worker running this generation stopped responding. Please retry."
        ),
    }
    log.error("idea_generator.failed", run_id=str(run_id), code=code, error=detail)
    completed_at = _utc_now()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(IdeaGenerationRunORM)
            .where(
                IdeaGenerationRunORM.id == run_id,
                IdeaGenerationRunORM.status == IdeaRunStatus.RUNNING.value,
                IdeaGenerationRunORM.worker_id == worker_id,
            )
            .values(
                status=IdeaRunStatus.FAILED.value,
                stage="failed",
                stage_progress=100,
                error_code=code,
                # Codes without a fixed message fall back to the detail the
                # pipeline attached -- BudgetExceeded, for instance, carries the
                # actual dollar figures -- and only then to a generic line.
                error_message=(
                    messages.get(code)
                    or (detail[:300] if detail else None)
                    or "Idea generation could not complete. Please retry."
                ),
                completed_at=completed_at,
                heartbeat_at=completed_at,
                lease_expires_at=None,
                worker_id=None,
                updated_at=completed_at,
            )
        )
        await db.commit()
        return (result.rowcount or 0) == 1


async def _generation_heartbeat(run_id: uuid.UUID, worker_id: str) -> None:
    while True:
        await asyncio.sleep(settings.idea_generator_worker_heartbeat_seconds)
        if not await _renew_generation_lease(run_id, worker_id):
            raise IdeaGenerationLeaseLost("idea_generation_lease_lost")


async def _execute_with_heartbeat(run_id: uuid.UUID, worker_id: str, execute) -> None:
    generation_task = asyncio.create_task(execute())
    heartbeat_task = asyncio.create_task(_generation_heartbeat(run_id, worker_id))
    tasks = {generation_task, heartbeat_task}
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if generation_task in done:
            await generation_task
            return
        error = heartbeat_task.exception()
        if error is not None:
            raise error
        raise IdeaGenerationLeaseLost("idea_generation_heartbeat_stopped")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _run_generation(run_id: uuid.UUID) -> None:
    claim = await _claim_generation_run(run_id)
    if claim is None:
        log.info(
            "idea_generator.claim_skipped",
            run_id=str(run_id),
            worker_id=_WORKER_ID,
        )
        return
    idea_format, attempt_count, started_at = claim
    worker_id = _WORKER_ID
    log.info(
        "idea_generator.claimed",
        run_id=str(run_id),
        worker_id=worker_id,
        attempt=attempt_count,
    )

    async def execute() -> None:
        async def on_stage(stage: str, progress: int) -> None:
            if not await _set_generation_stage(run_id, worker_id, stage, progress):
                raise IdeaGenerationLeaseLost("idea_generation_lease_lost")

        result = await _get_agent().generate(idea_format, on_stage=on_stage)
        if not await _set_generation_stage(run_id, worker_id, "saving_ideas", 92):
            raise IdeaGenerationLeaseLost("idea_generation_lease_lost")
        if not await _persist_generation_result(run_id, worker_id, result):
            raise IdeaGenerationLeaseLost("idea_generation_lease_lost")

    remaining_seconds = max(
        0.0,
        settings.idea_generator_total_timeout_seconds
        - (_utc_now() - started_at).total_seconds(),
    )
    if remaining_seconds <= 0:
        await _mark_generation_failed(
            run_id,
            worker_id,
            code="generation_timed_out",
            detail="overall idea-generation deadline expired before recovery",
        )
        return

    try:
        await asyncio.wait_for(
            _execute_with_heartbeat(run_id, worker_id, execute),
            timeout=remaining_seconds,
        )
    except asyncio.TimeoutError:
        await _mark_generation_failed(
            run_id,
            worker_id,
            code="generation_timed_out",
            detail="overall idea-generation deadline exceeded",
        )
    except IdeaGenerationLeaseLost:
        # A different process reclaimed this run after our lease expired. The
        # replacement worker now owns terminal persistence, so this stale worker
        # must stop without overwriting its status.
        log.warning(
            "idea_generator.lease_lost",
            run_id=str(run_id),
            worker_id=worker_id,
        )
    except asyncio.CancelledError:
        # Shutdown/reload intentionally leaves the lease in place. Another live
        # backend will reclaim it after expiry and restart the bounded run.
        log.info(
            "idea_generator.worker_cancelled",
            run_id=str(run_id),
            worker_id=worker_id,
        )
        raise
    except Exception as exc:
        known_codes = {
            "insufficient_evidence",
            "research_timed_out",
            "synthesis_timed_out",
            "repair_timed_out",
            "budget_exceeded",
        }
        code = str(exc) if str(exc) in known_codes else "generation_failed"
        # Flatten multiline validation errors so logs retain the failing field.
        detail = " | ".join(str(exc).split("\n"))[:600]
        if isinstance(exc, BudgetExceeded):
            # The bare code says nothing useful to whoever is reading the UI.
            detail = exc.detail
        await _mark_generation_failed(
            run_id,
            worker_id,
            code=code,
            detail=detail,
        )


def _schedule_generation(run_id: uuid.UUID) -> bool:
    existing = _GENERATION_TASKS.get(run_id)
    if existing is not None and not existing.done():
        return False

    task = asyncio.create_task(
        _run_generation(run_id),
        name=f"idea-generation-{run_id}",
    )
    _GENERATION_TASKS[run_id] = task

    def _finished(finished: asyncio.Task) -> None:
        if _GENERATION_TASKS.get(run_id) is finished:
            _GENERATION_TASKS.pop(run_id, None)
        if finished.cancelled():
            return
        error = finished.exception()
        if error is not None:
            log.error(
                "idea_generator.worker_crashed",
                run_id=str(run_id),
                error=str(error),
            )

    task.add_done_callback(_finished)
    return True


async def recover_expired_idea_generations() -> int:
    """Schedule queued work and reclaim only runs whose worker lease expired."""
    now = _utc_now()
    active_statuses = [IdeaRunStatus.QUEUED.value, IdeaRunStatus.RUNNING.value]
    expired = or_(
        IdeaGenerationRunORM.lease_expires_at.is_(None),
        IdeaGenerationRunORM.lease_expires_at <= now,
    )
    async with AsyncSessionLocal() as db:
        exhausted_result = await db.execute(
            update(IdeaGenerationRunORM)
            .where(
                IdeaGenerationRunORM.status.in_(active_statuses),
                IdeaGenerationRunORM.attempt_count >= settings.idea_generator_max_worker_attempts,
                or_(
                    IdeaGenerationRunORM.status == IdeaRunStatus.QUEUED.value,
                    expired,
                ),
            )
            .values(
                status=IdeaRunStatus.FAILED.value,
                stage="failed",
                stage_progress=100,
                error_code="interrupted",
                error_message=_INTERRUPTED_MESSAGE,
                completed_at=now,
                heartbeat_at=now,
                lease_expires_at=None,
                worker_id=None,
                updated_at=now,
            )
        )
        candidates = await db.execute(
            select(IdeaGenerationRunORM.id).where(
                IdeaGenerationRunORM.status.in_(active_statuses),
                IdeaGenerationRunORM.attempt_count < settings.idea_generator_max_worker_attempts,
                or_(
                    IdeaGenerationRunORM.status == IdeaRunStatus.QUEUED.value,
                    and_(
                        IdeaGenerationRunORM.status == IdeaRunStatus.RUNNING.value,
                        expired,
                    ),
                ),
            )
        )
        run_ids = list(candidates.scalars().all())
        await db.commit()

    scheduled = sum(1 for run_id in run_ids if _schedule_generation(run_id))
    if scheduled:
        log.info(
            "idea_generator.recovery_scheduled",
            worker_id=_WORKER_ID,
            count=scheduled,
        )
    exhausted = exhausted_result.rowcount or 0
    if exhausted:
        log.warning("idea_generator.recovery_exhausted", count=exhausted)
    return scheduled


async def run_idea_generation_recovery_loop() -> None:
    while True:
        try:
            await recover_expired_idea_generations()
        except Exception as exc:
            log.error("idea_generator.recovery_loop_error", error=str(exc))
        await asyncio.sleep(settings.idea_generator_recovery_poll_seconds)


async def shutdown_idea_generation_workers() -> None:
    tasks = [task for task in _GENERATION_TASKS.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _GENERATION_TASKS.clear()


async def _create_run(
    *,
    payload: IdeaGenerationCreate,
    idempotency_key: str,
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
    _schedule_generation(run.id)
    return await _load_run(db, run.id, user_id)


@router.post("", response_model=IdeaGenerationRunRead, status_code=status.HTTP_202_ACCEPTED)
async def create_idea_generation(
    payload: IdeaGenerationCreate,
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
    # Admins see every user's idea history (attributed by owner email);
    # everyone else sees only their own runs. Same rule as research sessions.
    stmt = (
        select(IdeaGenerationRunORM, UserORM.email)
        .options(selectinload(IdeaGenerationRunORM.ideas))
        .outerjoin(UserORM, IdeaGenerationRunORM.user_id == UserORM.id)
        .order_by(IdeaGenerationRunORM.created_at.desc())
        .limit(limit)
    )
    if not current_user.is_admin:
        stmt = stmt.where(IdeaGenerationRunORM.user_id == current_user.id)
    result = await db.execute(stmt)
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
            owner_email=owner_email if current_user.is_admin else None,
        )
        for run, owner_email in result.all()
    ]


@router.get("/{run_id}", response_model=IdeaGenerationRunRead)
async def get_idea_generation(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> IdeaGenerationRunRead:
    return _run_read(
        await _load_run(db, run_id, current_user.id, allow_any_owner=current_user.is_admin)
    )


@router.post("/{run_id}/retry", response_model=IdeaGenerationRunRead, status_code=status.HTTP_202_ACCEPTED)
async def retry_idea_generation(
    run_id: uuid.UUID,
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
    # "Active" has to mean a worker is genuinely still on it. Checking status
    # alone made a run whose worker had died -- killed by a deploy or a machine
    # restart -- undeletable: it stayed RUNNING until recovery got to it, and
    # every delete returned 409 with nothing the user could do about it. A live
    # lease is the real test, so an abandoned run can be cleared immediately.
    lease_expires_at = run.lease_expires_at
    worker_is_live = (
        lease_expires_at is not None
        and lease_expires_at.replace(tzinfo=lease_expires_at.tzinfo or timezone.utc) > _utc_now()
    )
    if run.status in {IdeaRunStatus.QUEUED.value, IdeaRunStatus.RUNNING.value} and worker_is_live:
        raise HTTPException(
            status_code=409,
            detail="This run is still generating. Wait for it to finish, or retry it once it stops.",
        )
    await db.execute(delete(IdeaGenerationRunORM).where(IdeaGenerationRunORM.id == run.id))
    await db.commit()


@router.delete("/ideas/{idea_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_generated_idea(
    idea_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> None:
    """Remove a single generated idea for good.

    Dismiss only hides an idea behind the "Show dismissed" toggle, which is the
    right default for one a producer might reconsider. This is for the ones they
    want gone -- the run's other ideas, its sources and its signals are
    untouched, since those are shared across the run.
    """
    idea = await _load_idea(db, idea_id, current_user.id)
    await db.execute(delete(GeneratedIdeaORM).where(GeneratedIdeaORM.id == idea.id))
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
