"""
Stories API routes — CRUD + pipeline trigger endpoints.
"""

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.graph.journalist_graph import journalist_graph
from backend.graph.state import create_initial_state
from backend.models.story import (
    FinalScript,
    StoryCreate,
    StoryListItem,
    StoryORM,
    StoryRead,
    StoryStatus,
)

log = structlog.get_logger(__name__)
router = APIRouter()


# ── Background pipeline runner ────────────────────────────────────────────────

_NODE_STATUS_MAP: dict[str, StoryStatus] = {
    "researcher": StoryStatus.RESEARCHING,
    "analyst": StoryStatus.ANALYSING,
    "storyline_creator": StoryStatus.WRITING_STORYLINE,
    "evaluator": StoryStatus.EVALUATING,
    "scriptwriter": StoryStatus.SCRIPTING,
}


async def _run_pipeline(story_id: str, topic: str, tone: str) -> None:
    """Run the full LangGraph journalist pipeline as a background task."""
    from backend.db.database import AsyncSessionLocal

    log.info("pipeline.started", story_id=story_id)

    initial_state = create_initial_state(topic=topic, story_id=story_id, tone=tone)

    # Stream graph updates so we can track per-node status in the database
    final_state: dict = dict(initial_state)
    try:
        async for chunk in journalist_graph.astream(initial_state, stream_mode="updates"):
            node_name = next(iter(chunk))
            node_updates = chunk[node_name]
            final_state.update(node_updates)

            new_status = _NODE_STATUS_MAP.get(node_name)
            if new_status:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(StoryORM)
                        .where(StoryORM.id == uuid.UUID(story_id))
                        .values(status=new_status)
                    )
                    await db.commit()
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

    # Persist final results
    script: Optional[FinalScript] = final_state.get("final_script")
    evaluation = final_state.get("evaluation_report")

    async with AsyncSessionLocal() as db:
        values = {
            "status": StoryStatus.COMPLETED if script else StoryStatus.FAILED,
            "script_data": script.model_dump(mode="json") if script else None,
            "script_s3_key": final_state.get("script_s3_key"),
            "quality_score": evaluation.overall_score if evaluation else None,
            "word_count": script.total_word_count if script else None,
            "estimated_duration_minutes": script.estimated_duration_minutes if script else None,
            "research_data": (
                final_state["research_package"].model_dump(mode="json")
                if final_state.get("research_package") else None
            ),
            "storyline_data": (
                final_state["selected_storyline"].model_dump(mode="json")
                if final_state.get("selected_storyline") else None
            ),
            "evaluation_data": (
                evaluation.model_dump(mode="json") if evaluation else None
            ),
            "error_message": final_state.get("error"),
        }
        if script:
            values["title"] = script.title

        await db.execute(
            update(StoryORM).where(StoryORM.id == uuid.UUID(story_id)).values(**values)
        )
        await db.commit()

    log.info("pipeline.complete", story_id=story_id, status=values["status"])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=StoryRead, status_code=status.HTTP_202_ACCEPTED)
async def create_story(
    payload: StoryCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
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
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)

    background_tasks.add_task(
        _run_pipeline,
        story_id=str(story.id),
        topic=story.topic,
        tone=story.tone,
    )

    log.info("stories.created", story_id=str(story.id), topic=story.topic)
    return story


@router.get("/", response_model=list[StoryListItem])
async def list_stories(
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[StoryStatus] = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[StoryORM]:
    """List all stories with optional status filter and pagination."""
    stmt = select(StoryORM).order_by(StoryORM.created_at.desc()).limit(limit).offset(offset)
    if status_filter:
        stmt = stmt.where(StoryORM.status == status_filter)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{story_id}", response_model=StoryRead)
async def get_story(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> StoryORM:
    """Retrieve a single story by ID including all pipeline artefacts."""
    result = await db.execute(select(StoryORM).where(StoryORM.id == story_id))
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status_code=404, detail=f"Story {story_id} not found")
    return story


@router.get("/{story_id}/script", response_model=FinalScript)
async def get_script(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FinalScript:
    """Return the final production script for a completed story."""
    result = await db.execute(select(StoryORM).where(StoryORM.id == story_id))
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status_code=404, detail=f"Story {story_id} not found")
    if not story.script_data:
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail=f"Script not yet available. Current status: {story.status}",
        )
    return FinalScript(**story.script_data)


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a story and all associated artefacts from the database."""
    result = await db.execute(select(StoryORM).where(StoryORM.id == story_id))
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status_code=404, detail=f"Story {story_id} not found")
    await db.delete(story)
    await db.commit()
    log.info("stories.deleted", story_id=str(story_id))
