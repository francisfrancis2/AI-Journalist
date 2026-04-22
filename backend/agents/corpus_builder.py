"""
CorpusBuilderAgent — one-time agent that builds benchmark reference corpora.

Run manually via:
    python -m backend.scripts.build_corpus

Workflow:
  1. Fetch 25-50 reference documentaries from YouTube (metadata + transcripts)
  2. Extract structural features from each transcript using Claude Haiku
  3. Synthesise cross-corpus patterns using Claude Sonnet
  4. Write pattern library to DB + local JSON cache
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.benchmark import (
    BIPatternLibrary,
    BIPatternLibraryORM,
    BIReferenceDocORM,
    DocStructure,
)
from backend.tools.youtube_fetcher import YouTubeFetcher

log = structlog.get_logger(__name__)


class InsufficientBenchmarkCorpusError(RuntimeError):
    """Raised when a rebuild cannot produce enough usable reference docs."""

    def __init__(
        self,
        *,
        library_key: str,
        have: int,
        need: int,
        fetched_videos: int = 0,
        new_videos: int = 0,
        missing_transcripts: int = 0,
        extraction_failures: int = 0,
    ) -> None:
        detail = (
            f"Benchmark corpus '{library_key}' has {have} usable docs; "
            f"minimum is {need}. Aborting without saving a pattern library."
        )
        if fetched_videos or new_videos or missing_transcripts or extraction_failures:
            detail = (
                f"{detail} Fetched {fetched_videos} candidate videos, "
                f"processed {new_videos} new videos, "
                f"{missing_transcripts} had no transcript, "
                f"and {extraction_failures} failed structure extraction."
            )
        super().__init__(detail)
        self.library_key = library_key
        self.have = have
        self.need = need


# ── Structure extraction prompt ───────────────────────────────────────────────

_EXTRACT_SYSTEM = """You are a documentary structure analyst. Given a YouTube documentary transcript,
extract its structural features. Be precise and data-driven."""


class _PatternSynthesisOutput(BaseModel):
    avg_act_count: float
    avg_act_duration_seconds: float
    hook_type_distribution: dict[str, float]
    title_formula_distribution: dict[str, float]
    closing_device_distribution: dict[str, float]
    avg_stat_count: float
    avg_rhetorical_questions: float
    human_story_act_avg: float
    sample_hooks: list[str] = Field(max_length=5)
    key_observations: list[str]


_SYNTHESISE_SYSTEM_TEMPLATE = """You are a documentary research analyst. Given structural data from multiple
{channel_label} YouTube documentaries, synthesise the common patterns that make them successful.
Focus on patterns that are consistent across the corpus and actionable for scoring new storylines."""


class CorpusBuilderAgent:
    """
    Builds and updates benchmark reference corpora.

    Example::

        agent = CorpusBuilderAgent(db)
        library = await agent.build(max_docs=25)
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._fetcher = YouTubeFetcher()
        self._haiku = ChatAnthropic(
            model=settings.claude_haiku_model,
            api_key=settings.anthropic_api_key,
            max_tokens=1024,
            temperature=0.1,
        ).with_structured_output(DocStructure)
        self._sonnet = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=2048,
            temperature=0.1,
        ).with_structured_output(_PatternSynthesisOutput)

    async def _extract_structure(self, title: str, transcript: str) -> Optional[DocStructure]:
        """Extract structural features from a single transcript using Haiku."""
        # Limit transcript to ~6000 tokens for efficiency
        excerpt = transcript[:24_000]
        try:
            return await self._haiku.ainvoke([
                SystemMessage(content=_EXTRACT_SYSTEM),
                HumanMessage(content=(
                    f"Title: {title}\n\n"
                    f"Transcript (may be truncated):\n{excerpt}\n\n"
                    "Extract the structural features of this documentary."
                )),
            ])
        except Exception as exc:
            log.warning("corpus_builder.extract_failed", title=title, error=str(exc))
            return None

    async def _synthesise_patterns(
        self,
        docs: list[BIReferenceDocORM],
        structures: list[DocStructure],
        titles: list[str],
        channel_label: str = "Business Insider",
    ) -> BIPatternLibrary:
        """Synthesise cross-corpus patterns from all extracted structures using Sonnet."""
        structures_text = "\n\n".join(
            f"Doc {i+1}: {title}\n{s.model_dump_json(indent=2)}"
            for i, (title, s) in enumerate(zip(titles, structures))
        )

        system = _SYNTHESISE_SYSTEM_TEMPLATE.format(channel_label=channel_label)
        output: _PatternSynthesisOutput = await self._sonnet.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=(
                f"Corpus: {len(structures)} {channel_label} documentaries\n\n"
                f"All titles:\n" + "\n".join(f"  - {t}" for t in titles) + "\n\n"
                f"Structural data:\n{structures_text}"
            )),
        ])

        return BIPatternLibrary(
            version=1,
            doc_count=len(structures),
            avg_act_count=output.avg_act_count,
            avg_act_duration_seconds=output.avg_act_duration_seconds,
            hook_type_distribution=output.hook_type_distribution,
            title_formula_distribution=output.title_formula_distribution,
            closing_device_distribution=output.closing_device_distribution,
            avg_stat_count=output.avg_stat_count,
            avg_rhetorical_questions=output.avg_rhetorical_questions,
            human_story_act_avg=output.human_story_act_avg,
            sample_hooks=output.sample_hooks,
            sample_titles=titles,
        )

    async def _get_next_version(self, library_key: str) -> int:
        result = await self._db.execute(
            select(BIPatternLibraryORM)
            .where(BIPatternLibraryORM.library_key == library_key)
            .order_by(BIPatternLibraryORM.version.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        return (latest.version + 1) if latest else 1

    async def _save_library(
        self, library: BIPatternLibrary, library_key: str
    ) -> None:
        """Persist pattern library to DB and local JSON cache."""
        if library.doc_count < settings.bi_corpus_min_docs:
            raise InsufficientBenchmarkCorpusError(
                library_key=library_key,
                have=library.doc_count,
                need=settings.bi_corpus_min_docs,
            )

        version = await self._get_next_version(library_key)
        library.version = version

        orm = BIPatternLibraryORM(
            id=uuid.uuid4(),
            library_key=library_key,
            version=version,
            doc_count=library.doc_count,
            patterns=library.model_dump(),
            created_at=datetime.now(timezone.utc),
        )
        self._db.add(orm)
        await self._db.commit()

        # Write JSON cache for fast loading in BenchmarkAgent
        cache_path = Path(settings.get_pattern_cache_path(library_key))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(library.model_dump_json(indent=2))

        log.info(
            "corpus_builder.library_saved",
            library_key=library_key,
            version=version,
            doc_count=library.doc_count,
        )

    async def build(
        self,
        max_docs: int = 50,
        library_key: str = "bi",
        channel_label: str = "Business Insider",
        channel_identifier: Optional[str] = None,
    ) -> BIPatternLibrary:
        """
        Full corpus build pipeline for any supported channel. Skips videos already in DB.

        Args:
            max_docs: Maximum number of docs to fetch and process.
            library_key: Library identifier ("bi", "cnbc", "vox", "jh").
            channel_label: Human-readable channel name used in prompts.
            channel_identifier: YouTube channel ID or @handle. Falls back to config.

        Returns:
            The synthesised BIPatternLibrary saved to DB.
        """
        channel_id = channel_identifier or settings.get_channel_identifier(library_key)
        log.info(
            "corpus_builder.start",
            library_key=library_key,
            channel_label=channel_label,
            max_docs=max_docs,
        )

        # 1. Fetch video list from YouTube
        videos = await self._fetcher.get_channel_videos(
            channel_id=channel_id, max_results=max_docs + 10
        )
        log.info("corpus_builder.videos_fetched", count=len(videos))

        # 2. Skip videos already in DB for this library
        existing = await self._db.execute(
            select(BIReferenceDocORM.youtube_id)
            .where(BIReferenceDocORM.library_key == library_key)
        )
        existing_ids = {row[0] for row in existing.fetchall()}
        new_videos = [v for v in videos if v["id"] not in existing_ids][:max_docs]
        log.info("corpus_builder.new_videos", count=len(new_videos))

        # 3. Fetch transcripts in parallel
        transcripts = await self._fetcher.get_transcripts_batch(
            [v["id"] for v in new_videos], concurrency=5
        )

        # 4. Extract structure + save each doc
        structures: list[DocStructure] = []
        titles: list[str] = []
        saved_docs: list[BIReferenceDocORM] = []
        missing_transcript_count = 0
        extraction_failure_count = 0

        for video in new_videos:
            transcript = transcripts.get(video["id"])
            if not transcript:
                missing_transcript_count += 1
                log.warning("corpus_builder.no_transcript", video_id=video["id"], title=video["title"])
                continue

            structure = await self._extract_structure(video["title"], transcript)
            if not structure:
                extraction_failure_count += 1
                continue

            doc = BIReferenceDocORM(
                id=uuid.uuid4(),
                library_key=library_key,
                youtube_id=video["id"],
                title=video["title"],
                description=video["description"],
                view_count=video["view_count"],
                like_count=video["like_count"],
                duration_seconds=video["duration_seconds"],
                transcript=transcript,
                extracted_structure=structure.model_dump(),
                created_at=datetime.now(timezone.utc),
            )
            self._db.add(doc)
            await self._db.commit()

            structures.append(structure)
            titles.append(video["title"])
            saved_docs.append(doc)
            log.info("corpus_builder.doc_processed", title=video["title"], library_key=library_key)

        # 5. Include already-existing docs for this library in synthesis
        new_video_ids = {v["id"] for v in new_videos}
        if existing_ids:
            existing_docs_result = await self._db.execute(
                select(BIReferenceDocORM).where(BIReferenceDocORM.library_key == library_key)
            )
            for existing_doc in existing_docs_result.scalars().all():
                if existing_doc.extracted_structure and existing_doc.youtube_id not in new_video_ids:
                    try:
                        structures.append(DocStructure(**existing_doc.extracted_structure))
                        titles.append(existing_doc.title)
                    except Exception:
                        pass

        if len(structures) < settings.bi_corpus_min_docs:
            log.error(
                "corpus_builder.insufficient_docs",
                library_key=library_key,
                have=len(structures),
                need=settings.bi_corpus_min_docs,
                fetched_videos=len(videos),
                new_videos=len(new_videos),
                missing_transcripts=missing_transcript_count,
                extraction_failures=extraction_failure_count,
            )
            raise InsufficientBenchmarkCorpusError(
                library_key=library_key,
                have=len(structures),
                need=settings.bi_corpus_min_docs,
                fetched_videos=len(videos),
                new_videos=len(new_videos),
                missing_transcripts=missing_transcript_count,
                extraction_failures=extraction_failure_count,
            )

        # 6. Synthesise patterns across full corpus
        log.info("corpus_builder.synthesising", library_key=library_key, doc_count=len(structures))
        library = await self._synthesise_patterns(
            saved_docs, structures, titles, channel_label=channel_label
        )

        # 7. Save to DB + cache
        await self._save_library(library, library_key=library_key)
        log.info("corpus_builder.complete", library_key=library_key, doc_count=library.doc_count)
        return library
