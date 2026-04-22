"""
Unit tests for benchmark corpus readiness helpers.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.models.benchmark import BIPatternLibrary
from backend.services.benchmarking import BenchmarkLibraryStatus, _status_from_library


def _library(doc_count: int) -> BIPatternLibrary:
    return BIPatternLibrary(
        version=1,
        doc_count=doc_count,
        avg_act_count=5.0,
        avg_act_duration_seconds=120.0,
        hook_type_distribution={"stat": 1.0},
        title_formula_distribution={"how_x_became_y": 1.0},
        closing_device_distribution={"forward_look": 1.0},
        avg_stat_count=8.0,
        avg_rhetorical_questions=2.0,
        human_story_act_avg=4.0,
        sample_hooks=["A sharp opening hook."],
        sample_titles=["Reference documentary"],
    )


def test_small_benchmark_library_is_not_ready_for_scoring():
    status = _status_from_library(
        _library(doc_count=1),
        library_key="bi",
        built_at=datetime.now(timezone.utc),
        cache_exists=True,
        cache_mtime=datetime.now(timezone.utc),
        notes=[],
    )

    assert status.available is True
    assert status.ready_for_scoring is False
    assert status.stale is True
    assert "below the recommended minimum" in " ".join(status.notes)


def test_sufficient_benchmark_library_is_ready_for_scoring():
    status = _status_from_library(
        _library(doc_count=25),
        library_key="bi",
        built_at=datetime.now(timezone.utc),
        cache_exists=True,
        cache_mtime=datetime.now(timezone.utc),
        notes=[],
    )

    assert status.available is True
    assert status.ready_for_scoring is True


@pytest.mark.asyncio
async def test_corpus_builder_does_not_save_empty_library(db_session):
    from backend.agents.corpus_builder import (
        CorpusBuilderAgent,
        InsufficientBenchmarkCorpusError,
    )
    from backend.models.benchmark import BIPatternLibraryORM

    class EmptyTranscriptFetcher:
        async def get_channel_videos(self, channel_id: str, max_results: int) -> list[dict]:
            return [
                {
                    "id": "video-1",
                    "title": "Reference video with blocked transcript",
                    "description": "",
                    "view_count": 1000,
                    "like_count": 100,
                    "duration_seconds": 600,
                }
            ]

        async def get_transcripts_batch(
            self, video_ids: list[str], concurrency: int = 5
        ) -> dict[str, None]:
            return {video_id: None for video_id in video_ids}

    agent = CorpusBuilderAgent.__new__(CorpusBuilderAgent)
    agent._db = db_session
    agent._fetcher = EmptyTranscriptFetcher()

    with pytest.raises(InsufficientBenchmarkCorpusError, match="Aborting without saving"):
        await agent.build(max_docs=1, library_key="bi", channel_identifier="test-channel")

    result = await db_session.execute(select(BIPatternLibraryORM))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_admin_status_recommends_rebuild_when_libraries_are_not_ready(
    db_session, monkeypatch
):
    from backend.services import benchmarking

    async def fake_load_benchmark_library(library_key: str, db):
        return None, BenchmarkLibraryStatus(
            key=library_key,
            label=library_key.upper(),
            description="",
            implemented=True,
            active=True,
            available=True,
            ready_for_scoring=False,
            version=1,
            doc_count=0,
            cache_exists=True,
            built_at=datetime.now(timezone.utc),
            cache_mtime=datetime.now(timezone.utc),
            notes=["Corpus is below the recommended minimum of 20 documents."],
        )

    monkeypatch.setattr(
        benchmarking, "load_benchmark_library", fake_load_benchmark_library
    )

    status = await benchmarking.get_benchmark_admin_status(db_session)

    assert status.libraries[0].key == "combined"
    assert status.libraries[0].available is False
    assert status.libraries[0].ready_for_scoring is False
    assert "below the minimum" in status.recommended_action
    assert "below the minimum" in " ".join(status.libraries[0].notes)
