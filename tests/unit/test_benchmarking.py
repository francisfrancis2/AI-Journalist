"""
Unit tests for benchmark corpus readiness helpers.
"""

from datetime import datetime, timedelta, timezone

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
async def test_corpus_refresh_replaces_only_one_quarter_with_fresh_videos(
    db_session, monkeypatch, tmp_path
):
    from backend.agents.corpus_builder import CorpusBuilderAgent
    from backend.config import settings
    from backend.models.benchmark import BIPatternLibraryORM, BIReferenceDocORM, DocStructure

    monkeypatch.setattr(settings, "bi_pattern_cache_path", str(tmp_path / "bi_patterns.json"))

    def structure(index: int = 0) -> DocStructure:
        return DocStructure(
            hook_type="stat",
            hook_text=f"Hook {index}",
            act_count=4,
            act_titles=["One", "Two", "Three", "Four"],
            act_durations_seconds=[120, 120, 120, 120],
            has_human_story=True,
            human_story_act=2,
            closing_device="forward_look",
            stat_count=5,
            rhetorical_question_count=1,
            title_formula="how_x_became_y",
        )

    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(20):
        db_session.add(
            BIReferenceDocORM(
                library_key="bi",
                youtube_id=f"old-{index}",
                title=f"Old reference {index}",
                description="Old reference",
                view_count=1_000 + index,
                like_count=100 + index,
                duration_seconds=600,
                transcript="Existing transcript",
                extracted_structure=structure(index).model_dump(),
                created_at=base_time + timedelta(minutes=index),
            )
        )
    await db_session.commit()

    class FreshVideoFetcher:
        def __init__(self) -> None:
            self.orders: list[str] = []

        async def get_channel_videos(
            self, channel_id: str, max_results: int, order: str = "viewCount"
        ) -> list[dict]:
            self.orders.append(order)
            return [
                {
                    "id": f"new-{index}",
                    "title": f"New reference {index}",
                    "description": "New reference",
                    "view_count": 2_000 + index,
                    "like_count": 200 + index,
                    "duration_seconds": 700,
                }
                for index in range(10)
            ]

        async def get_transcripts_batch(
            self, video_ids: list[str], concurrency: int = 1
        ) -> dict[str, str]:
            return {video_id: "Fresh transcript" for video_id in video_ids}

    fetcher = FreshVideoFetcher()
    agent = CorpusBuilderAgent.__new__(CorpusBuilderAgent)
    agent._db = db_session
    agent._fetcher = fetcher

    async def fake_extract(title: str, transcript: str) -> DocStructure:
        return structure(100)

    async def fake_synthesise(
        docs: list[BIReferenceDocORM],
        structures: list[DocStructure],
        titles: list[str],
        channel_label: str = "Business Insider",
    ) -> BIPatternLibrary:
        library = _library(doc_count=len(structures))
        library.sample_titles = titles
        return library

    agent._extract_structure = fake_extract
    agent._synthesise_patterns = fake_synthesise

    library = await agent.refresh_latest_fraction(
        max_docs=50,
        library_key="bi",
        channel_identifier="test-channel",
        refresh_fraction=0.25,
    )

    assert fetcher.orders == ["date"]
    assert library.doc_count == 20

    docs_result = await db_session.execute(
        select(BIReferenceDocORM).where(BIReferenceDocORM.library_key == "bi")
    )
    docs = docs_result.scalars().all()
    ids = {doc.youtube_id for doc in docs}

    assert len(docs) == 20
    assert {f"new-{index}" for index in range(5)}.issubset(ids)
    assert not {f"old-{index}" for index in range(5)} & ids
    assert {f"old-{index}" for index in range(5, 20)}.issubset(ids)

    library_result = await db_session.execute(select(BIPatternLibraryORM))
    library_rows = library_result.scalars().all()
    assert len(library_rows) == 1
    assert library_rows[0].doc_count == 20


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
