"""
Benchmark admin routes.

Provides corpus health, reference library visibility, and rebuild controls
for Benchmarking 2.0.
"""

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_admin_user
from backend.config import settings
from backend.db.database import get_db
from backend.models.user import UserORM
from backend.services.benchmarking import (
    BenchmarkAdminStatus,
    BenchmarkLibraryStatus,
    BenchmarkRebuildResponse,
    BenchmarkReferenceDocRead,
    _IMPLEMENTED_KEYS,
    get_benchmark_admin_status,
    list_benchmark_reference_docs,
    run_benchmark_rebuild,
)

log = structlog.get_logger(__name__)
router = APIRouter()


class BenchmarkRebuildRequest(BaseModel):
    library_key: str = Field("combined", min_length=2, max_length=32)


@router.get("/status", response_model=BenchmarkAdminStatus)
async def benchmark_status(
    db: AsyncSession = Depends(get_db),
) -> BenchmarkAdminStatus:
    """Return corpus availability, freshness, and active rebuild status."""
    return await get_benchmark_admin_status(db)


@router.get("/libraries", response_model=list[BenchmarkLibraryStatus])
async def benchmark_libraries(
    db: AsyncSession = Depends(get_db),
) -> list[BenchmarkLibraryStatus]:
    """Return the library catalog with current health information."""
    status_payload = await get_benchmark_admin_status(db)
    return status_payload.libraries


@router.get("/references", response_model=list[BenchmarkReferenceDocRead])
async def benchmark_references(
    library_key: str = Query("combined"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[BenchmarkReferenceDocRead]:
    """List reference documentaries in a benchmark corpus library."""
    return await list_benchmark_reference_docs(db, library_key=library_key, limit=limit, offset=offset)


@router.post("/rebuild", response_model=BenchmarkRebuildResponse, status_code=status.HTTP_202_ACCEPTED)
async def rebuild_benchmark_library(
    payload: BenchmarkRebuildRequest,
    background_tasks: BackgroundTasks,
    _admin: UserORM = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> BenchmarkRebuildResponse:
    """
    Trigger a background corpus rebuild for the requested library.
    By default rebuilds the combined benchmark corpus across all component libraries.
    """
    if payload.library_key not in _IMPLEMENTED_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Library '{payload.library_key}' is not a valid implemented library key.",
        )

    status_payload = await get_benchmark_admin_status(db)
    if status_payload.build_in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A benchmark rebuild is already in progress.",
        )

    docs = settings.benchmark_default_rebuild_docs
    background_tasks.add_task(
        run_benchmark_rebuild,
        library_key=payload.library_key,
        max_docs=docs,
    )
    log.info("benchmarks.rebuild_requested", library_key=payload.library_key, docs=docs)

    return BenchmarkRebuildResponse(
        accepted=True,
        library_key=payload.library_key,
        requested_docs=docs,
        message=f"Benchmark rebuild for '{payload.library_key}' started in the background.",
    )
