"""Tests for the pooled trend corpus.

Research used to be run-scoped and cascaded away with the run. This store is
keyed by content so it survives the run that found it, accumulates across users,
and ages out on last_seen_at rather than first_seen_at.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.models.idea_generation import TrendObservationORM
from backend.services.trend_memory import (
    KIND_SOURCE,
    content_hash,
    format_for_prompt,
    load_recent_observations,
    purge_expired_observations,
    record_observations,
)


def _row(title: str, url: str | None = None, **over):
    return {
        "content_hash": content_hash(url, title),
        "kind": KIND_SOURCE,
        "title": title,
        "url": url,
        "domain": over.get("domain", "example.ae"),
        "excerpt": over.get("excerpt", "A UAE business development with figures."),
        "published_at": over.get("published_at"),
        "credibility": over.get("credibility", "high"),
        "is_uae_relevant": over.get("is_uae_relevant", True),
        "payload": {},
    }


class TestIdentity:
    def test_same_story_from_two_providers_is_one_observation(self):
        assert content_hash("https://x.ae/a", "Jebel Ali volumes") == content_hash(
            "https://X.AE/a ", " jebel ali volumes"
        )

    def test_different_stories_differ(self):
        assert content_hash("https://x.ae/a", "A") != content_hash("https://x.ae/b", "B")


class TestRecording:
    @pytest.mark.asyncio
    async def test_a_repeat_bumps_seen_count_instead_of_duplicating(self, db_session):
        await record_observations(db_session, [_row("Jebel Ali volumes", "https://x.ae/1")])
        await record_observations(db_session, [_row("Jebel Ali volumes", "https://x.ae/1")])

        rows = (await db_session.execute(select(TrendObservationORM))).scalars().all()
        assert len(rows) == 1, "the same story must not be stored twice"
        assert rows[0].seen_count == 2, "a resurfacing story is a durable trend"

    @pytest.mark.asyncio
    async def test_rows_without_a_title_are_skipped(self, db_session):
        bad = _row("")
        assert await record_observations(db_session, [bad]) == 0


class TestReadBack:
    @pytest.mark.asyncio
    async def test_recurring_observations_rank_above_one_offs(self, db_session):
        await record_observations(db_session, [_row("Seen once", "https://x.ae/once")])
        for _ in range(3):
            await record_observations(db_session, [_row("Seen often", "https://x.ae/often")])

        loaded = await load_recent_observations(db_session)
        assert loaded[0].title == "Seen often"

    @pytest.mark.asyncio
    async def test_observations_outside_the_window_are_not_loaded(self, db_session):
        await record_observations(db_session, [_row("Old news", "https://x.ae/old")])
        row = (await db_session.execute(select(TrendObservationORM))).scalars().one()
        row.last_seen_at = datetime.now(timezone.utc) - timedelta(days=200)
        await db_session.commit()

        assert await load_recent_observations(db_session, window_days=90) == []


class TestPromptRendering:
    def test_every_line_states_its_age(self):
        """Age is load-bearing: this show turns on "why now"."""
        row = TrendObservationORM(
            content_hash="h", kind=KIND_SOURCE, title="Jebel Ali volumes",
            excerpt="Figures.", domain="wam.ae", credibility="high",
            is_uae_relevant=True, seen_count=1,
            last_seen_at=datetime.now(timezone.utc) - timedelta(days=42),
        )
        rendered = format_for_prompt([row])
        assert "[42d old]" in rendered
        assert "Jebel Ali volumes" in rendered

    def test_recurrence_is_surfaced(self):
        row = TrendObservationORM(
            content_hash="h", kind=KIND_SOURCE, title="Recurring story",
            excerpt="x", domain="wam.ae", credibility="high", is_uae_relevant=True,
            seen_count=4, last_seen_at=datetime.now(timezone.utc),
        )
        assert "seen in 4 runs" in format_for_prompt([row])

    def test_empty_input_renders_nothing(self):
        assert format_for_prompt([]) == ""


class TestRetention:
    @pytest.mark.asyncio
    async def test_purge_removes_only_what_is_past_the_window(self, db_session):
        await record_observations(db_session, [
            _row("Fresh", "https://x.ae/fresh"),
            _row("Stale", "https://x.ae/stale"),
        ])
        stale = (await db_session.execute(
            select(TrendObservationORM).where(TrendObservationORM.title == "Stale")
        )).scalars().one()
        stale.last_seen_at = datetime.now(timezone.utc) - timedelta(days=120)
        await db_session.commit()

        deleted = await purge_expired_observations(db_session, retention_days=90)
        assert deleted == 1
        remaining = (await db_session.execute(select(TrendObservationORM))).scalars().all()
        assert [r.title for r in remaining] == ["Fresh"]

    @pytest.mark.asyncio
    async def test_a_recurring_story_survives_past_its_first_sighting(self, db_session):
        """Retention runs on last_seen_at, so a live trend is not aged out."""
        await record_observations(db_session, [_row("Long-running", "https://x.ae/long")])
        row = (await db_session.execute(select(TrendObservationORM))).scalars().one()
        # Both set explicitly: SQLite stores no timezone, so leaving last_seen_at
        # to the driver mixes naive and aware values in the comparison.
        row.first_seen_at = datetime.now(timezone.utc) - timedelta(days=200)
        row.last_seen_at = datetime.now(timezone.utc)
        await db_session.commit()

        assert await purge_expired_observations(db_session, retention_days=90) == 0

    @pytest.mark.asyncio
    async def test_retention_disabled_deletes_nothing(self, db_session):
        await record_observations(db_session, [_row("Keep", "https://x.ae/keep")])
        assert await purge_expired_observations(db_session, retention_days=0) == 0
