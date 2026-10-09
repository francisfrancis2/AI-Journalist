"""The pooled UAE trend corpus: what every past run already found out.

Research used to be re-fetched from scratch on every run and then thrown away
with it. This keeps it, pooled across all users, so each generation starts from
what is already known and adds to it.

Three rules shape everything here:

* **Keyed by content, not by run.** The same story reaches us from several
  providers, and a run that gets deleted must not take its research with it.
* **Retention runs on last_seen_at.** A source that keeps resurfacing is a
  durable trend and stays; a one-off ages out of the window.
* **Age travels with the observation.** This show turns on *why now*, so a
  three-month-old source silently supporting a fresh claim is the failure mode
  worth engineering against -- see ``format_for_prompt``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.idea_generation import TrendObservationORM

log = structlog.get_logger(__name__)

KIND_SOURCE = "source"
KIND_SIGNAL = "signal"
KIND_DEEP_REPORT = "deep_report"


def content_hash(*parts: Optional[str]) -> str:
    """Stable identity for an observation, independent of who fetched it."""
    joined = "|".join((part or "").strip().lower() for part in parts)
    return hashlib.sha256(joined.encode("utf-8", errors="ignore")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def record_observations(
    db: AsyncSession, rows: Iterable[dict[str, Any]]
) -> int:
    """Upsert observations, bumping last_seen_at and seen_count on a repeat.

    Writes are best-effort by design: this corpus makes future runs better, so
    failing to record must never fail the run that produced it. The caller logs
    and continues.
    """
    payloads = [row for row in rows if row.get("content_hash") and row.get("title")]
    if not payloads:
        return 0

    now = _utc_now()
    # One statement, so a concurrent run recording the same story is a bump
    # rather than a unique-violation.
    statement = pg_insert(TrendObservationORM).values(
        [{**row, "first_seen_at": now, "last_seen_at": now, "seen_count": 1} for row in payloads]
    )
    statement = statement.on_conflict_do_update(
        index_elements=[TrendObservationORM.content_hash],
        set_={
            "last_seen_at": now,
            "seen_count": TrendObservationORM.seen_count + 1,
            # Refresh the excerpt: a later fetch of the same story is usually
            # the fuller one.
            "excerpt": statement.excluded.excerpt,
        },
    )
    await db.execute(statement)
    await db.commit()
    return len(payloads)


async def load_recent_observations(
    db: AsyncSession,
    *,
    kind: str = KIND_SOURCE,
    limit: Optional[int] = None,
    window_days: Optional[int] = None,
) -> list[TrendObservationORM]:
    """Prior research worth putting in front of the model.

    Not simply the newest rows. Ranking prefers observations that have
    resurfaced across runs, then UAE relevance, then credibility, then recency,
    so one busy news week cannot crowd out everything else in the window.
    """
    window = window_days or settings.idea_research_retention_days
    cap = limit or settings.idea_research_prior_source_limit
    cutoff = _utc_now() - timedelta(days=window)

    result = await db.execute(
        select(TrendObservationORM)
        .where(
            TrendObservationORM.kind == kind,
            TrendObservationORM.last_seen_at >= cutoff,
        )
        .order_by(
            TrendObservationORM.seen_count.desc(),
            TrendObservationORM.is_uae_relevant.desc(),
            TrendObservationORM.last_seen_at.desc(),
        )
        .limit(cap)
    )
    return list(result.scalars().all())


def format_for_prompt(observations: list[TrendObservationORM]) -> str:
    """Render prior research with its age stated on every line.

    The age is not decoration. Expert Mode and documentary ideas both rest on
    "why now", and a stale source supporting a fresh claim does not look like an
    error in the output -- it looks like a confident idea. Stating the age on
    every line is what lets the prompt require recency where it matters.
    """
    if not observations:
        return ""
    now = _utc_now()
    lines = []
    for item in observations:
        seen = item.last_seen_at or now
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        age_days = max(0, (now - seen).days)
        recurrence = f", seen in {item.seen_count} runs" if item.seen_count > 1 else ""
        lines.append(
            f"[{age_days}d old{recurrence}] {item.title}\n"
            f"  {item.domain or 'unknown source'} | credibility: {item.credibility}"
            f" | UAE-relevant: {item.is_uae_relevant}\n"
            f"  {item.excerpt[:400]}"
        )
    return "\n\n".join(lines)


async def purge_expired_observations(
    db: AsyncSession, *, retention_days: Optional[int] = None
) -> int:
    """Delete observations not seen inside the retention window."""
    retention = (
        settings.idea_research_retention_days if retention_days is None else retention_days
    )
    if retention <= 0:
        return 0
    cutoff = _utc_now() - timedelta(days=retention)
    result = await db.execute(
        delete(TrendObservationORM).where(TrendObservationORM.last_seen_at < cutoff)
    )
    await db.commit()
    return result.rowcount or 0


__all__ = [
    "KIND_DEEP_REPORT",
    "KIND_SIGNAL",
    "KIND_SOURCE",
    "content_hash",
    "format_for_prompt",
    "load_recent_observations",
    "purge_expired_observations",
    "record_observations",
]
