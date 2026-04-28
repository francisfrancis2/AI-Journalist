"""
Benchmarking service helpers shared by agents and admin routes.

This module centralises:
- library discovery and library catalog metadata
- cache/DB fallback loading for benchmark libraries
- freshness and health reporting
- in-process corpus rebuild state for admin visibility
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.database import AsyncSessionLocal
from backend.models.benchmark import (
    BIPatternLibrary,
    BIPatternLibraryORM,
    BIReferenceDocORM,
)

log = structlog.get_logger(__name__)

_ACTIVE_LIBRARY_KEY = "combined"
_COMPONENT_LIBRARY_KEYS = ("bi", "cnbc", "vox", "jh")

_SUPPORTED_LIBRARY_CATALOG = [
    {
        "key": "bi",
        "label": "Business Insider",
        "implemented": True,
        "active": True,
        "description": "Benchmark library based on Business Insider documentaries.",
    },
    {
        "key": "cnbc",
        "label": "CNBC Make It",
        "implemented": True,
        "active": True,
        "description": "Benchmark library for personality-led business storytelling.",
    },
    {
        "key": "vox",
        "label": "Vox",
        "implemented": True,
        "active": True,
        "description": "Benchmark library for explanatory and issue-driven documentaries.",
    },
    {
        "key": "jh",
        "label": "Johnny Harris",
        "implemented": True,
        "active": True,
        "description": "Benchmark library for immersive, first-person investigative storytelling.",
    },
]

_CATALOG_META: dict[str, dict] = {item["key"]: item for item in _SUPPORTED_LIBRARY_CATALOG}
_COMBINED_LIBRARY_META = {
    "key": _ACTIVE_LIBRARY_KEY,
    "label": "Benchmark Corpus",
    "implemented": True,
    "active": True,
    "description": "Combined benchmark corpus built from all active reference libraries.",
}

_BUILD_STATE: dict[str, object] = {
    "in_progress": False,
    "library_key": _ACTIVE_LIBRARY_KEY,
    "requested_docs": None,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


class BenchmarkLibraryStatus(BaseModel):
    """Admin-facing status for one benchmark library."""

    key: str
    label: str
    description: str
    implemented: bool
    active: bool
    available: bool
    ready_for_scoring: bool
    version: Optional[int] = None
    doc_count: int = 0
    minimum_doc_count: int = settings.bi_corpus_min_docs
    built_at: Optional[datetime] = None
    cache_exists: bool = False
    cache_mtime: Optional[datetime] = None
    stale: bool = False
    stale_after_days: int = settings.benchmark_corpus_stale_after_days
    notes: list[str] = Field(default_factory=list)


class BenchmarkAdminStatus(BaseModel):
    """Top-level benchmarking health snapshot for the admin workspace."""

    active_library_key: str
    build_in_progress: bool
    build_library_key: Optional[str] = None
    requested_docs: Optional[int] = None
    last_build_started_at: Optional[datetime] = None
    last_build_finished_at: Optional[datetime] = None
    last_build_error: Optional[str] = None
    recommended_action: str
    libraries: list[BenchmarkLibraryStatus]


class BenchmarkReferenceDocRead(BaseModel):
    """Minimal admin view of one benchmark reference documentary."""

    id: str
    youtube_id: str
    title: str
    description: Optional[str] = None
    view_count: int
    like_count: int
    duration_seconds: int
    has_transcript: bool
    created_at: datetime


class BenchmarkRebuildResponse(BaseModel):
    """Acknowledgement for a corpus rebuild request."""

    accepted: bool
    library_key: str
    requested_docs: int
    message: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _cache_mtime(path: Path) -> Optional[datetime]:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


async def _latest_library_row(db: AsyncSession, library_key: str) -> Optional[BIPatternLibraryORM]:
    result = await db.execute(
        select(BIPatternLibraryORM)
        .where(BIPatternLibraryORM.library_key == library_key)
        .order_by(BIPatternLibraryORM.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _status_from_library(
    library: Optional[BIPatternLibrary],
    *,
    library_key: str,
    built_at: Optional[datetime],
    cache_exists: bool,
    cache_mtime: Optional[datetime],
    notes: list[str],
) -> BenchmarkLibraryStatus:
    meta = _CATALOG_META.get(library_key, {
        "label": library_key.upper(),
        "description": "",
        "implemented": True,
        "active": True,
    })
    stale_cutoff = _utc_now() - timedelta(days=settings.benchmark_corpus_stale_after_days)
    doc_count = library.doc_count if library else 0
    stale = bool(built_at and built_at < stale_cutoff)
    if doc_count and doc_count < settings.bi_corpus_min_docs:
        stale = True

    ready_for_scoring = library is not None and doc_count >= settings.bi_corpus_min_docs
    if doc_count < settings.bi_corpus_min_docs and library is not None:
        notes.append(
            f"Corpus is below the recommended minimum of {settings.bi_corpus_min_docs} documents."
        )
    if stale and built_at:
        notes.append("Corpus is stale and should be refreshed.")
    if not cache_exists and library is not None:
        notes.append("Cache file missing or invalid; serving benchmark data from the database.")

    return BenchmarkLibraryStatus(
        key=library_key,
        label=str(meta["label"]),
        description=str(meta["description"]),
        implemented=bool(meta["implemented"]),
        active=bool(meta["active"]),
        available=library is not None,
        ready_for_scoring=ready_for_scoring,
        version=library.version if library else None,
        doc_count=doc_count,
        built_at=built_at,
        cache_exists=cache_exists,
        cache_mtime=cache_mtime,
        stale=stale,
        notes=notes,
    )


async def load_benchmark_library(
    library_key: str = "bi",
    *,
    db: Optional[AsyncSession] = None,
) -> tuple[Optional[BIPatternLibrary], BenchmarkLibraryStatus]:
    """
    Load a benchmark library by key, preferring cache but falling back to DB.

    Args:
        library_key: One of "bi", "cnbc", "vox", "jh".
        db: Optional async session. Creates one automatically if not provided.
    """
    cache_path = Path(settings.get_pattern_cache_path(library_key))
    cache_exists = cache_path.exists()
    cache_mtime = _cache_mtime(cache_path)
    cache_library: Optional[BIPatternLibrary] = None
    notes: list[str] = []

    if cache_exists:
        try:
            parsed = BIPatternLibrary.model_validate_json(cache_path.read_text())
            if parsed.doc_count > 0:
                cache_library = parsed
        except Exception as exc:
            notes.append("Cache file exists but could not be parsed.")
            log.warning("benchmarking.cache_invalid", library_key=library_key, error=str(exc))

    owns_session = db is None
    if owns_session:
        async with AsyncSessionLocal() as session:
            return await load_benchmark_library(library_key, db=session)

    latest_row = await _latest_library_row(db, library_key)
    db_library: Optional[BIPatternLibrary] = None
    built_at: Optional[datetime] = None

    if latest_row:
        try:
            db_library = BIPatternLibrary.model_validate(latest_row.patterns)
            built_at = latest_row.created_at
        except Exception as exc:
            notes.append("Latest DB library row exists but is invalid.")
            log.warning("benchmarking.db_library_invalid", library_key=library_key, error=str(exc))

    chosen: Optional[BIPatternLibrary] = None
    if cache_library and db_library:
        if cache_library.version == db_library.version:
            chosen = cache_library
        else:
            chosen = db_library
            notes.append("Cache version was behind the database version; database copy used.")
    elif cache_library:
        chosen = cache_library
        built_at = cache_mtime
        notes.append("Using cached benchmark library because no DB row was found.")
    elif db_library:
        chosen = db_library
        notes.append("Using DB-backed benchmark library because cache was unavailable.")
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(db_library.model_dump_json(indent=2))
            cache_exists = True
            cache_mtime = _cache_mtime(cache_path)
        except Exception as exc:
            notes.append("Failed to refresh the local cache from the database.")
            log.warning("benchmarking.cache_write_failed", library_key=library_key, error=str(exc))

    status = _status_from_library(
        chosen,
        library_key=library_key,
        built_at=built_at,
        cache_exists=cache_exists,
        cache_mtime=cache_mtime,
        notes=notes,
    )
    return chosen, status


async def load_active_benchmark_library(
    *,
    db: Optional[AsyncSession] = None,
) -> tuple[Optional[BIPatternLibrary], BenchmarkLibraryStatus]:
    """Load the combined benchmark library used for production scoring."""
    owns_session = db is None
    if owns_session:
        async with AsyncSessionLocal() as session:
            return await load_active_benchmark_library(db=session)

    assert db is not None
    loaded: list[tuple[BIPatternLibrary, BenchmarkLibraryStatus]] = []
    statuses: list[BenchmarkLibraryStatus] = []
    for key in _COMPONENT_LIBRARY_KEYS:
        library, status = await load_benchmark_library(key, db=db)
        statuses.append(status)
        if library is not None:
            loaded.append((library, status))

    notes: list[str] = []
    missing_count = sum(1 for status in statuses if not status.available)
    not_ready_count = sum(1 for status in statuses if not status.ready_for_scoring)
    stale_count = sum(1 for status in statuses if status.stale)
    if missing_count:
        notes.append("One or more component corpora are missing and should be rebuilt.")
    if not_ready_count and not missing_count:
        notes.append("One or more component corpora are below the minimum size for scoring.")
    if stale_count:
        notes.append("One or more component corpora are stale and should be refreshed.")
    if missing_count or not_ready_count or not loaded:
        return None, BenchmarkLibraryStatus(
            key=_ACTIVE_LIBRARY_KEY,
            label=str(_COMBINED_LIBRARY_META["label"]),
            description=str(_COMBINED_LIBRARY_META["description"]),
            implemented=True,
            active=True,
            available=False,
            ready_for_scoring=False,
            doc_count=sum(status.doc_count for status in statuses),
            cache_exists=all(status.cache_exists for status in statuses),
            stale=bool(stale_count),
            notes=notes,
        )

    total_docs = sum(max(library.doc_count, 0) for library, _ in loaded)
    if total_docs <= 0:
        total_docs = len(loaded)

    def _weighted_average(field: str) -> float:
        return sum(
            getattr(library, field) * max(library.doc_count, 1)
            for library, _ in loaded
        ) / total_docs

    def _weighted_distribution(field: str) -> dict[str, float]:
        totals: dict[str, float] = {}
        for library, _ in loaded:
            weight = max(library.doc_count, 1)
            distribution = getattr(library, field)
            for key, value in distribution.items():
                totals[key] = totals.get(key, 0.0) + (value * weight)
        return {key: value / total_docs for key, value in totals.items()}

    sample_hooks: list[str] = []
    sample_titles: list[str] = []
    for library, _ in loaded:
        sample_hooks.extend(library.sample_hooks[:5])
        sample_titles.extend(library.sample_titles[:12])

    combined = BIPatternLibrary(
        version=max((library.version for library, _ in loaded), default=1),
        doc_count=sum(library.doc_count for library, _ in loaded),
        avg_act_count=_weighted_average("avg_act_count"),
        avg_act_duration_seconds=_weighted_average("avg_act_duration_seconds"),
        hook_type_distribution=_weighted_distribution("hook_type_distribution"),
        title_formula_distribution=_weighted_distribution("title_formula_distribution"),
        closing_device_distribution=_weighted_distribution("closing_device_distribution"),
        avg_stat_count=_weighted_average("avg_stat_count"),
        avg_rhetorical_questions=_weighted_average("avg_rhetorical_questions"),
        human_story_act_avg=_weighted_average("human_story_act_avg"),
        sample_hooks=sample_hooks[:12],
        sample_titles=sample_titles[:40],
    )

    built_dates = [status.built_at for _, status in loaded if status.built_at]
    cache_dates = [status.cache_mtime for _, status in loaded if status.cache_mtime]
    status = BenchmarkLibraryStatus(
        key=_ACTIVE_LIBRARY_KEY,
        label=str(_COMBINED_LIBRARY_META["label"]),
        description=str(_COMBINED_LIBRARY_META["description"]),
        implemented=True,
        active=True,
        available=True,
        ready_for_scoring=missing_count == 0 and all(status.ready_for_scoring for _, status in loaded),
        version=combined.version,
        doc_count=combined.doc_count,
        built_at=min(built_dates) if built_dates else None,
        cache_exists=all(status.cache_exists for _, status in loaded),
        cache_mtime=min(cache_dates) if cache_dates else None,
        stale=bool(stale_count),
        notes=notes,
    )
    return combined, status


async def get_benchmark_admin_status(db: AsyncSession) -> BenchmarkAdminStatus:
    """Return benchmark admin status including all library health and build state."""
    library_statuses: list[BenchmarkLibraryStatus] = []
    any_stale = False
    any_missing = False
    any_not_ready = False

    for item in _SUPPORTED_LIBRARY_CATALOG:
        key = str(item["key"])
        _, lib_status = await load_benchmark_library(key, db=db)
        library_statuses.append(lib_status)
        if not lib_status.available:
            any_missing = True
        if not lib_status.ready_for_scoring:
            any_not_ready = True
        elif lib_status.stale:
            any_stale = True

    if any_missing:
        recommended_action = (
            "One or more benchmark libraries have not been built yet. "
            "Run a complete corpus rebuild to enable full benchmarking coverage."
        )
    elif any_not_ready:
        recommended_action = (
            f"One or more benchmark libraries are below the minimum of "
            f"{settings.bi_corpus_min_docs} documents. Run a complete corpus rebuild."
        )
    elif any_stale:
        recommended_action = "One or more benchmark libraries are stale and should be refreshed."
    else:
        recommended_action = "All benchmark libraries are healthy."

    combined_missing = any_missing
    combined_not_ready = any_not_ready
    combined_stale = any_stale
    combined_built_dates = [status.built_at for status in library_statuses if status.built_at]
    combined_cache_dates = [status.cache_mtime for status in library_statuses if status.cache_mtime]
    combined_versions = [status.version for status in library_statuses if status.version is not None]

    return BenchmarkAdminStatus(
        active_library_key=_ACTIVE_LIBRARY_KEY,
        build_in_progress=bool(_BUILD_STATE["in_progress"]),
        build_library_key=_BUILD_STATE["library_key"] if _BUILD_STATE["in_progress"] else None,
        requested_docs=_BUILD_STATE["requested_docs"] if _BUILD_STATE["in_progress"] else None,
        last_build_started_at=_BUILD_STATE["started_at"],
        last_build_finished_at=_BUILD_STATE["finished_at"],
        last_build_error=_BUILD_STATE["error"],
        recommended_action=recommended_action,
        libraries=[
            BenchmarkLibraryStatus(
                key=_ACTIVE_LIBRARY_KEY,
                label=str(_COMBINED_LIBRARY_META["label"]),
                description=str(_COMBINED_LIBRARY_META["description"]),
                implemented=True,
                active=True,
                available=not combined_missing and not combined_not_ready,
                ready_for_scoring=not combined_missing and all(
                    status.ready_for_scoring for status in library_statuses
                ),
                version=max(combined_versions) if combined_versions else None,
                doc_count=sum(status.doc_count for status in library_statuses),
                built_at=min(combined_built_dates) if combined_built_dates else None,
                cache_exists=all(status.cache_exists for status in library_statuses),
                cache_mtime=min(combined_cache_dates) if combined_cache_dates else None,
                stale=combined_stale,
                notes=(
                    ["One or more component corpora are missing."]
                    if combined_missing
                    else ["One or more component corpora are below the minimum document count."]
                    if combined_not_ready
                    else ["One or more component corpora should be refreshed."]
                    if combined_stale
                    else []
                ),
            ),
            *library_statuses,
        ],
    )


async def list_benchmark_reference_docs(
    db: AsyncSession,
    *,
    library_key: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> list[BenchmarkReferenceDocRead]:
    """List reference docs for the admin workspace. Filters by library_key when provided."""
    query = select(BIReferenceDocORM)
    if library_key == _ACTIVE_LIBRARY_KEY:
        query = query.where(BIReferenceDocORM.library_key.in_(_COMPONENT_LIBRARY_KEYS))
    elif library_key:
        query = query.where(BIReferenceDocORM.library_key == library_key)
    query = query.order_by(BIReferenceDocORM.view_count.desc(), BIReferenceDocORM.created_at.desc())
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    docs = result.scalars().all()
    return [
        BenchmarkReferenceDocRead(
            id=str(doc.id),
            youtube_id=doc.youtube_id,
            title=doc.title,
            description=doc.description,
            view_count=doc.view_count,
            like_count=doc.like_count,
            duration_seconds=doc.duration_seconds,
            has_transcript=bool(doc.transcript),
            created_at=doc.created_at,
        )
        for doc in docs
    ]


_IMPLEMENTED_KEYS = {
    _ACTIVE_LIBRARY_KEY,
    *{str(item["key"]) for item in _SUPPORTED_LIBRARY_CATALOG if item["implemented"]},
}


async def run_benchmark_rebuild(
    *,
    library_key: str = "bi",
    max_docs: Optional[int] = None,
    refresh_fraction: Optional[float] = None,
) -> None:
    """Run a corpus rebuild in-process and update admin-visible build state."""
    from backend.agents.corpus_builder import CorpusBuilderAgent

    if library_key not in _IMPLEMENTED_KEYS:
        raise ValueError(f"Benchmark library '{library_key}' is not implemented.")

    docs = max_docs or settings.benchmark_default_rebuild_docs

    _BUILD_STATE.update(
        in_progress=True,
        library_key=library_key,
        requested_docs=docs,
        started_at=_utc_now(),
        finished_at=None,
        error=None,
    )

    try:
        async with AsyncSessionLocal() as db:
            agent = CorpusBuilderAgent(db)
            target_keys = (
                _COMPONENT_LIBRARY_KEYS
                if library_key == _ACTIVE_LIBRARY_KEY
                else (library_key,)
            )
            for target_key in target_keys:
                meta = _CATALOG_META[target_key]
                channel_label = str(meta["label"])
                channel_identifier = settings.get_channel_identifier(target_key)
                if refresh_fraction is not None:
                    await agent.refresh_latest_fraction(
                        max_docs=docs,
                        library_key=target_key,
                        channel_label=channel_label,
                        channel_identifier=channel_identifier,
                        refresh_fraction=refresh_fraction,
                    )
                else:
                    await agent.build(
                        max_docs=docs,
                        library_key=target_key,
                        channel_label=channel_label,
                        channel_identifier=channel_identifier,
                    )
        _BUILD_STATE["finished_at"] = _utc_now()
        _BUILD_STATE["error"] = None
    except Exception as exc:
        _BUILD_STATE["finished_at"] = _utc_now()
        _BUILD_STATE["error"] = str(exc)
        log.error("benchmarking.rebuild_failed", library_key=library_key, error=str(exc))
        raise
    finally:
        _BUILD_STATE["in_progress"] = False
