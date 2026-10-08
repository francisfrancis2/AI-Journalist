"""Evidence-first UAE business idea generation agent (V2)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.agents.research import ResearchAgent
from backend.config import settings
from backend.services.cost_ledger import (
    BudgetExceeded,
    CostLedger,
    estimate_tokens,
    ledger_config,
    use_ledger,
)
from backend.services.prompt_loader import load_prompt
from backend.models.idea_generation import IdeaFormat
from backend.models.research import RawSource, ResearchPackage
from backend.tools.vidiq import VidIQTool

log = structlog.get_logger(__name__)

_UAE_RE = re.compile(
    r"\b(uae|united arab emirates|dubai|abu dhabi|sharjah|ajman|fujairah|"
    r"ras al khaimah|umm al quwain|emirati)\b",
    re.IGNORECASE,
)
_POLICY_SUBJECT_RE = re.compile(
    r"\b(uae|emirates?|government|rulers?|royal family|institutions?|ministry|authority)\b",
    re.IGNORECASE,
)
_POLICY_NEGATIVE_RE = re.compile(
    r"\b(corrupt(?:ion)?|cover[- ]?up|regime|oppression|dictator(?:ship)?|"
    r"state failure|government failure|royal scandal|institutional scandal)\b",
    re.IGNORECASE,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdeaCandidate(StrictModel):
    # These caps are a guard against runaway output, not a style rule. They
    # used to sit at normal verbosity: a production run failed outright because
    # two candidates wrote business_significance slightly over 900 characters,
    # and because structured output validates the whole CandidateSet at once,
    # two long paragraphs destroyed four candidates' work. The DB columns are
    # Text with no limit, so nothing downstream needed the tight bound. Target
    # lengths are stated in idea_generator_shared.md so the model can comply --
    # the previous failure was partly that it was never told.
    sector: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=8, max_length=220)
    premise: str = Field(min_length=30, max_length=1600)
    why_now: str = Field(min_length=20, max_length=1200)
    uae_relevance: str = Field(min_length=20, max_length=1200)
    central_tension: str = Field(min_length=15, max_length=1000)
    target_audience: str = Field(min_length=5, max_length=300)
    business_significance: str = Field(min_length=20, max_length=1600)
    format_details: dict[str, Any]
    source_ids: list[str] = Field(min_length=2, max_length=8)
    # min_length=1: vidIQ signals were collected (51 per run) but almost never
    # cited, because source_ids was required and this was not. The asymmetry,
    # not the collection, is why demand data looked 'not pulled'.
    signal_keys: list[str] = Field(min_length=1, max_length=8)
    verification_gaps: list[str] = Field(default_factory=list, max_length=6)

    # Character budgets stated in the prompt and enforced above are still only
    # a request: the model can exceed them, and because structured output
    # validates the whole CandidateSet at once, one long paragraph fails every
    # candidate in the set. That is how a production run lost four ideas and
    # ~$0.50 of work to two sentences of overrun.
    #
    # Raising the caps made that less likely. Trimming makes it impossible: an
    # over-long field is cut back to its limit at a word boundary instead of
    # rejected. A slightly shortened paragraph is plainly better than a failed
    # run, and the overrun is logged so prompt drift stays visible.
    @field_validator(
        "premise", "why_now", "uae_relevance", "central_tension",
        "target_audience", "business_significance", "title", "sector",
        mode="before",
    )
    @classmethod
    def _trim_to_budget(cls, value: Any, info: Any) -> Any:
        if not isinstance(value, str):
            return value
        field = cls.model_fields.get(info.field_name)
        limit = getattr(field, "metadata", None) and next(
            (m.max_length for m in field.metadata if hasattr(m, "max_length")), None
        )
        if not limit or len(value) <= limit:
            return value
        cut = value[:limit]
        # Prefer a clean break so the text does not end mid-word.
        boundary = cut.rfind(" ")
        trimmed = (cut[:boundary] if boundary > limit * 0.6 else cut).rstrip(" ,;:")
        log.warning(
            "idea_generator.field_trimmed",
            field=info.field_name,
            original_length=len(value),
            limit=limit,
        )
        return trimmed


class CandidateSet(StrictModel):
    candidates: list[IdeaCandidate] = Field(min_length=1, max_length=12)


class PreparedSource(StrictModel):
    id: uuid.UUID
    reference_id: str
    title: str
    url: str | None = None
    domain: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    excerpt: str
    source_type: str
    credibility: str
    is_uae_relevant: bool
    is_primary: bool
    content_hash: str
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class PreparedSignal(StrictModel):
    id: uuid.UUID
    key: str
    provider: str
    signal_type: str
    topic: str
    query: str | None = None
    geography: str | None = None
    geography_meaning: str | None = None
    observed_at: datetime | None = None
    window_days: int | None = None
    metric: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    source_url: str | None = None
    domain: str | None = None
    reliability: str = "medium"
    is_cached: bool = False
    raw_reference: dict[str, Any] = Field(default_factory=dict)


class ScoredIdea(StrictModel):
    rank: int = 0
    candidate: IdeaCandidate
    score_breakdown: dict[str, float]
    score: float
    strength: str
    source_ids: list[uuid.UUID]
    signal_ids: list[uuid.UUID]


class IdeaGenerationResult(StrictModel):
    ideas: list[ScoredIdea]
    sources: list[PreparedSource]
    signals: list[PreparedSignal]
    provider_statuses: dict[str, dict[str, Any]]
    coverage_reasons: list[str]
    candidate_metrics: dict[str, Any]
    usage_metrics: dict[str, Any]


def _safe_json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return {"value": str(value)[:1000]}


def _source_type(source: RawSource) -> str:
    return getattr(source.source_type, "value", str(source.source_type))


def _credibility(source: RawSource) -> str:
    return getattr(source.credibility, "value", str(source.credibility))


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
        return host.removeprefix("www.") or None
    except ValueError:
        return None


def _prepare_sources(package: ResearchPackage) -> list[PreparedSource]:
    prepared: list[PreparedSource] = []
    seen: set[str] = set()
    for source in package.sources:
        if _source_type(source) == "youtube_benchmark":
            continue
        url = (source.url or "").strip() or None
        domain = _domain(url)
        key = url or f"{source.title}|{source.content[:120]}"
        digest = hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        reference_id = str(source.source_id)
        text = " ".join(filter(None, [source.title, source.content, url or ""]))
        prepared.append(
            PreparedSource(
                id=uuid.uuid4(),
                reference_id=reference_id,
                title=(source.title or domain or "Untitled source")[:1000],
                url=url,
                domain=domain,
                publisher=source.author,
                published_at=source.published_at,
                excerpt=(source.content or "")[:1400],
                source_type=_source_type(source),
                credibility=_credibility(source),
                is_uae_relevant=bool(_UAE_RE.search(text) or (domain and domain.endswith(".ae"))),
                is_primary=bool((source.metadata or {}).get("primary_source")),
                content_hash=digest,
                raw_metadata={
                    **_safe_json(source.metadata or {}),
                    "research_source_id": reference_id,
                    "relevance_score": source.relevance_score,
                },
            )
        )
    return prepared[:60]


def _walk_rows(value: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                rows.append((path, item))
    elif isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            rows.extend(_walk_rows(child, child_path))
    return rows


def _row_get(row: dict[str, Any], *names: str) -> Any:
    """Case-insensitive lookup across a vidIQ row.

    vidIQ is inconsistent between tools: the keyword tool returns ``keyword``
    while the video and outlier tools return ``VideoTitle`` and ``VideoId``. A
    lowercase-only lookup found no title on any video row, so every one fell
    back to the literal label "YouTube opportunity signal" and the real title
    surfaced only inside a raw key/value dump.
    """
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _video_url(row: dict[str, Any]) -> Optional[str]:
    """A watchable link for a signal row, built from the id when none is given."""
    url = _row_get(row, "url", "videoUrl")
    if url:
        return str(url)
    video_id = _row_get(row, "videoId", "id")
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else None


# Plumbing that carries no meaning for a producer reading an idea card. The
# title is already the signal's topic, so repeating it in values was what made
# the card read as a dump.
_SIGNAL_NOISE_KEYS = {
    "videothumbnail", "thumbnail", "thumbnails", "etag", "kind", "id",
    "videoid", "channelid", "playlistid", "url", "videourl", "description",
    # Whatever _prepare_signals used as the topic: repeating it in values is
    # the duplication that made the signal block read as a dump.
    "videotitle", "title", "keyword", "question", "name",
}


# Matched as substrings, because vidIQ prefixes the same field per entity:
# "thumbnail" alone misses "channelThumbnail" and "videoThumbnail".
_SIGNAL_NOISE_SUBSTRINGS = ("thumbnail", "etag", "playlist")

# vidIQ fills unavailable fields with these rather than omitting them. Printing
# "Unknown" next to a real number is exactly the kind of noise that made the
# block unreadable.
_SIGNAL_EMPTY_VALUES = {"", "unknown", "n/a", "na", "none", "null"}


def _signal_values(row: dict[str, Any]) -> dict[str, Any]:
    """Keep the fields worth reading, drop the plumbing.

    Curated here rather than in the UI so the synthesis model sees the same
    clean set the user does. Two vidIQ habits need handling: publish dates come
    back as unix seconds, which displayed as a bare ten-digit number, and
    durations come back as raw seconds.
    """
    values: dict[str, Any] = {}
    for key, value in row.items():
        name = str(key)
        lowered = name.lower()
        if lowered in _SIGNAL_NOISE_KEYS:
            continue
        if any(token in lowered for token in _SIGNAL_NOISE_SUBSTRINGS):
            continue
        if not isinstance(value, (str, int, float, bool)):
            continue
        if isinstance(value, str) and value.strip().lower() in _SIGNAL_EMPTY_VALUES:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "publish" in lowered and value > 1_000_000_000:
                value = datetime.fromtimestamp(float(value), tz=timezone.utc).date().isoformat()
            elif "duration" in lowered and 0 < value < 86_400:
                value = f"{int(value) // 60}:{int(value) % 60:02d}"
        values[name] = value
        if len(values) >= 6:
            break
    return values


def _prepare_signals(raw: dict[str, Any] | None) -> list[PreparedSignal]:
    """Flatten vidIQ's broad trend payloads into citable signals.

    Idea discovery deliberately uses the broad tools -- UAE country keyword
    volume, global rising keywords, UAE-channel trending videos and channel
    outliers -- rather than the single-topic demand report the Research
    workspace and story path use. There is no topic yet at this point in the
    run; finding what is moving is the job.

    Rows that cannot be named are skipped rather than emitted under a generic
    label. A signal only reaches the user if synthesis cited it for an idea, and
    an unnameable row would surface there as a cryptic line with nothing to
    read, which is worse than the idea simply showing no signal.
    """
    if not raw:
        return []
    signals: list[PreparedSignal] = []
    semantics = raw.get("geography_semantics") or {}
    skipped = 0
    for group, payload in (raw.get("payloads") or {}).items():
        for index, (path, row) in enumerate(_walk_rows(payload)):
            if len(signals) >= 60:
                break
            topic = _row_get(row, "keyword", "videoTitle", "title", "question", "name")
            if not topic:
                skipped += 1
                continue
            topic = str(topic)
            signal_type = (
                "keyword_demand" if "keyword" in group
                else "view_velocity" if "trending" in group
                else "video_outlier" if "outlier" in group
                else "youtube_signal"
            )
            signal_id = uuid.uuid4()
            key = f"{group}:{index}:{hashlib.sha1(topic.encode()).hexdigest()[:8]}"
            metric = (
                "country_volume" if group == "uae_country_keywords"
                else "views_per_hour" if "trending" in group
                else "breakout_score"
            )
            signals.append(
                PreparedSignal(
                    id=signal_id,
                    key=key,
                    provider="vidiq",
                    signal_type=signal_type,
                    topic=topic[:500],
                    query="UAE business economy technology entrepreneurship",
                    # Every remaining trend call is AE-scoped; the one global
                    # group was removed from fetch_idea_trends.
                    geography="AE",
                    geography_meaning=semantics.get(group),
                    observed_at=datetime.now(timezone.utc),
                    window_days=int(raw.get("window_days") or 30),
                    metric=metric,
                    values=_signal_values(row),
                    source_url=_video_url(row),
                    domain="youtube.com" if "video" in group or "outlier" in group else None,
                    reliability="medium",
                    raw_reference={"group": group, "path": path},
                )
            )
    log.info("idea_generator.signals_prepared", kept=len(signals), unnameable_skipped=skipped)
    return signals


def _is_current_uae_source(source: PreparedSource) -> bool:
    if not source.is_uae_relevant or source.credibility == "low":
        return False
    if source.published_at:
        published = source.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return published >= datetime.now(timezone.utc) - timedelta(days=45)
    return source.source_type in {"news_api", "rss", "web_search", "web_scrape"}


def _policy_conflict(candidate: IdeaCandidate) -> bool:
    text = " ".join(
        [candidate.title, candidate.premise, candidate.uae_relevance, candidate.central_tension]
    )
    return bool(_POLICY_SUBJECT_RE.search(text) and _POLICY_NEGATIVE_RE.search(text))


def _score_candidate(
    candidate: IdeaCandidate,
    source_map: dict[str, PreparedSource],
    signal_map: dict[str, PreparedSignal],
) -> tuple[ScoredIdea | None, str | None]:
    sources = [source_map[source_id] for source_id in candidate.source_ids if source_id in source_map]
    signals = [signal_map[key] for key in candidate.signal_keys if key in signal_map]
    domains = {source.domain for source in sources if source.domain}

    # Two independent domains and a current UAE source used to be pass/fail
    # gates here. That made validation, rather than the brief, decide how many
    # ideas a run produced — a five-candidate synthesis routinely yielded two.
    # They are scored below instead: a thinly sourced idea ranks beneath a
    # well-sourced one rather than vanishing. The criteria still reach the
    # model as requirements in idea_generator_shared.md, so they shape what
    # gets written instead of what survives.
    #
    # Two things stay hard, because neither is a matter of degree: a candidate
    # whose SOURCE_IDs resolve to nothing is citing evidence that does not
    # exist, and editorial policy is a line rather than a score.
    if not sources:
        return None, "no_resolvable_sources"
    if _policy_conflict(candidate):
        return None, "editorial_policy_conflict"

    independent_sourcing = len(sources) >= 2 and len(domains) >= 2
    current_uae = any(_is_current_uae_source(source) for source in sources)
    if not (independent_sourcing and current_uae):
        log.info(
            "idea_generator.soft_criteria_missed",
            title=candidate.title[:80],
            independent_sourcing=independent_sourcing,
            current_uae_source=current_uae,
            source_count=len(sources),
            domain_count=len(domains),
        )

    uae = min(20.0, 12.0 + 2.0 * sum(source.is_uae_relevant for source in sources))
    # Missing either former gate costs most of that component's points, so the
    # ranking still prefers candidates that meet both.
    timeliness = (
        min(20.0, 10.0 + 3.0 * sum(_is_current_uae_source(source) for source in sources))
        if current_uae
        else 4.0
    )
    youtube = min(15.0, 5.0 + 2.5 * len(signals)) if signals else 3.0
    significance = min(15.0, 8.0 + len(candidate.business_significance) / 180.0 + len(sources))
    editorial = min(15.0, 8.0 + len(candidate.central_tension) / 120.0 + len(candidate.format_details))
    feasibility = min(10.0, 5.0 + len(candidate.format_details))
    evidence = (
        min(5.0, 1.0 + len(domains) + 0.5 * sum(source.credibility == "high" for source in sources))
        if independent_sourcing
        else 0.0
    )
    breakdown = {
        "uae_relevance": round(uae, 1),
        "timeliness": round(timeliness, 1),
        "youtube_opportunity": round(youtube, 1),
        "business_significance": round(significance, 1),
        "editorial_strength": round(editorial, 1),
        "production_feasibility": round(feasibility, 1),
        "evidence_quality": round(evidence, 1),
    }
    total = round(sum(breakdown.values()), 1)
    strength = "strong" if total >= 80 else "promising" if total >= 65 else "developing"
    return (
        ScoredIdea(
            candidate=candidate,
            score_breakdown=breakdown,
            score=total,
            strength=strength,
            source_ids=[source.id for source in sources],
            signal_ids=[signal.id for signal in signals],
        ),
        None,
    )


def _source_digest(
    sources: list[PreparedSource],
    *,
    limit: int = 40,
    excerpt_chars: int = 650,
) -> str:
    rows = []
    for source in sources[:limit]:
        rows.append(
            f"SOURCE_ID={source.reference_id}\nTitle: {source.title}\n"
            f"Domain: {source.domain or 'unknown'} | Published: {source.published_at or 'unknown'} | "
            f"Credibility: {source.credibility} | UAE-relevant: {source.is_uae_relevant}\n"
            f"Evidence: {source.excerpt[:excerpt_chars]}"
        )
    return "\n\n".join(rows)


def _signal_digest(signals: list[PreparedSignal], *, limit: int = 35) -> str:
    return "\n".join(
        f"SIGNAL_KEY={signal.key} | {signal.signal_type} | {signal.topic} | "
        f"Geography meaning: {signal.geography_meaning or 'not geographic'} | "
        f"Values: {json.dumps(signal.values, default=str)[:450]}"
        for signal in signals[:limit]
    )


class _Deadline:
    """A single wall-clock ceiling that every phase of a run must fit inside.

    Per-phase budgets are nominal: :meth:`allot` hands out the smaller of the
    phase budget and the time actually left. That way a phase that overruns
    cannot borrow time from the ones after it, and the run as a whole cannot
    outlast the ceiling — which is what makes "never more than five minutes" a
    guarantee rather than the sum of four hopeful numbers.
    """

    def __init__(self, total_seconds: float) -> None:
        self._expires_at = time.monotonic() + max(0.0, total_seconds)

    @property
    def remaining(self) -> float:
        return max(0.0, self._expires_at - time.monotonic())

    def allot(self, phase_budget: float) -> float:
        return min(float(phase_budget), self.remaining)


async def _bounded(awaitable, *, timeout: float, error_code: str):
    """Apply an attributable wall-clock bound to an external phase."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise RuntimeError(error_code) from exc


StageCallback = Callable[[str, int], Awaitable[None]]


_SUBJECT_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "how", "why", "what",
    "uae", "dubai", "abu", "dhabi", "emirates", "business", "company", "new",
    "its", "into", "are", "was", "has", "can", "but", "not", "you", "they",
}


def _subject_tokens(candidate: "IdeaCandidate") -> set[str]:
    """Distinctive words identifying what an idea is actually about.

    Region words are stopped: in a UAE newsroom every idea mentions the UAE, so
    leaving them in would make unrelated stories look similar.
    """
    text = f"{candidate.title} {candidate.premise}".lower()
    return {w for w in re.findall(r"[a-z][a-z0-9'-]{2,}", text) if w not in _SUBJECT_STOP}


def _same_subject(a: "IdeaCandidate", b: "IdeaCandidate", threshold: float = 0.28) -> bool:
    """True when two candidates are really the same story in different clothes.

    Sector labels alone are not enough — two ideas can be filed under different
    sectors while covering the same company or funding round.
    """
    ta, tb = _subject_tokens(a), _subject_tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return overlap >= threshold



class IdeaGeneratorAgent:
    """Researches, verifies, ranks, and returns supported UAE business ideas."""

    def __init__(self) -> None:
        # Idea synthesis is structured evidence summarisation, so Sonnet gives
        # materially lower latency than Opus while preserving the same schema
        # and deterministic validation below.
        llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=settings.idea_generator_synthesis_max_tokens,
        )
        self._structured_llm = llm.with_structured_output(CandidateSet)
        repair_llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=settings.idea_generator_repair_max_tokens,
        )
        self._repair_structured_llm = repair_llm.with_structured_output(CandidateSet)
        self._research = ResearchAgent()

    async def generate(
        self,
        idea_format: IdeaFormat,
        *,
        on_stage: StageCallback | None = None,
    ) -> IdeaGenerationResult:
        """Run one generation inside a fresh spend ceiling and wall-clock deadline.

        The ledger is published on the context for the whole run, so the research
        tools charge their own spend without needing it passed down to them.
        """
        ledger = CostLedger(budget_usd=settings.idea_generator_max_cost_usd)
        deadline = _Deadline(
            settings.idea_generator_total_timeout_seconds
            - settings.idea_generator_persist_reserve_seconds
        )
        with use_ledger(ledger):
            return await self._generate(
                idea_format,
                on_stage=on_stage,
                ledger=ledger,
                deadline=deadline,
            )

    async def _generate(
        self,
        idea_format: IdeaFormat,
        *,
        on_stage: StageCallback | None,
        ledger: CostLedger,
        deadline: _Deadline,
    ) -> IdeaGenerationResult:
        format_label = "documentary" if idea_format == IdeaFormat.DOCUMENTARY else "expert interview video"
        research_prompt = (
            "Identify current, evidence-backed business developments and emerging topics in the "
            "United Arab Emirates from the last 30 days that could support original English-language "
            f"{format_label} ideas. Search across technology, finance, logistics, energy, real estate, "
            "retail, tourism, aviation, healthcare, food, climate, manufacturing, and entrepreneurship. "
            "Prioritize primary sources, reputable UAE reporting, named companies, data, people, and "
            "filmable change. Keep discussion of the UAE, its government, rulers and institutions neutral "
            "or constructive; reject a topic if compliance would require hiding or distorting evidence."
        )
        package, vidiq_raw = await _bounded(
            asyncio.gather(
                self._research.gather_initial_package(
                    prompt=research_prompt,
                    deep=True,
                    include_vidiq=False,
                    rss_country="AE",
                    deep_max_uses=settings.anthropic_deep_research_idea_max_uses,
                    # This caps only Anthropic server-side web-search uses.
                    # Tavily, NewsAPI, RSS, scraping, and retained source count
                    # are unchanged.
                ),
                # Idea discovery needs vidIQ's broad trend surface -- country
                # keyword volume, rising keywords, UAE-channel trending videos
                # and channel outliers -- not the single-topic demand report the
                # Research workspace and story path use. There is no topic yet;
                # finding what is moving is the job.
                VidIQTool().fetch_idea_trends(window_days=30),
            ),
            timeout=deadline.allot(settings.idea_generator_research_timeout_seconds),
            error_code="research_timed_out",
        )
        sources = _prepare_sources(package)
        signals = _prepare_signals(vidiq_raw)
        if len({source.domain for source in sources if source.domain}) < 2:
            raise RuntimeError("insufficient_evidence")
        if on_stage is not None:
            await on_stage("synthesizing_ideas", 65)

        source_map = {source.reference_id: source for source in sources}
        signal_map = {signal.key: signal for signal in signals}
        rejected: dict[str, int] = {}
        accepted: list[ScoredIdea] = []
        synthesis_calls = 0

        # Prompts live in backend/prompts/*.md so editors can change them without
        # touching Python. Read per call, so local edits apply to the next run.
        format_prompt_name = (
            "idea_generator_documentary"
            if idea_format == IdeaFormat.DOCUMENTARY
            else "idea_generator_expert"
        )
        system_prompt = (
            load_prompt("idea_generator_shared").format(
                candidate_count=settings.idea_generator_candidate_count,
                result_count=settings.idea_generator_result_count,
            )
            + "\n\n"
            + load_prompt(format_prompt_name)
        )

        def accept_candidates(candidates: list[IdeaCandidate]) -> None:
            for candidate in candidates:
                if any(existing.candidate.title.casefold() == candidate.title.casefold() for existing in accepted):
                    rejected["duplicate_title"] = rejected.get("duplicate_title", 0) + 1
                    continue
                scored, reason = _score_candidate(candidate, source_map, signal_map)
                if scored is None:
                    rejected[reason or "validation_failed"] = rejected.get(reason or "validation_failed", 0) + 1
                    continue
                accepted.append(scored)

        def _synthesis_human(limit: int, excerpt_chars: int) -> str:
            return (
                f"Today is {datetime.now(timezone.utc).date().isoformat()}.\n"
                f"Requested format: {idea_format.value}.\n\nFACTUAL SOURCES:\n"
                f"{_source_digest(sources, limit=limit, excerpt_chars=excerpt_chars)}\n\n"
                f"VIDIQ OPPORTUNITY SIGNALS:\n{_signal_digest(signals) or '(vidIQ unavailable)'}"
            )

        # Research has already charged the ledger, so what is left here is the
        # real headroom. Prefer a thinner evidence digest over a failed run:
        # step the payload down until its worst case fits, and only refuse when
        # even the smallest digest would breach the ceiling.
        synthesis_payload_steps = ((40, 650), (30, 450), (20, 320))
        human_content = _synthesis_human(*synthesis_payload_steps[0])
        for step in synthesis_payload_steps:
            human_content = _synthesis_human(*step)
            if ledger.affords(
                model=settings.claude_model,
                input_tokens=estimate_tokens(system_prompt + human_content),
                max_output_tokens=settings.idea_generator_synthesis_max_tokens,
            ):
                if step != synthesis_payload_steps[0]:
                    log.warning(
                        "idea_generator.synthesis_payload_trimmed",
                        source_limit=step[0],
                        excerpt_chars=step[1],
                        remaining_usd=round(ledger.remaining_usd, 4),
                    )
                break
        else:
            # Re-run the check as a reservation so the failure carries the
            # actual dollar figures rather than a bare code.
            ledger.reserve(
                phase="synthesis",
                model=settings.claude_model,
                input_tokens=estimate_tokens(system_prompt + human_content),
                max_output_tokens=settings.idea_generator_synthesis_max_tokens,
            )

        synthesis_calls += 1
        result = await _bounded(
            self._structured_llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=human_content),
                ],
                config=ledger_config("synthesis"),
            ),
            timeout=deadline.allot(settings.idea_generator_synthesis_timeout_seconds),
            error_code="synthesis_timed_out",
        )
        accept_candidates(result.candidates)

        # Never repeat the full six-candidate synthesis. If deterministic
        # validation leaves a deficit, request only the missing candidates with
        # a compact evidence subset and a much smaller time/output budget.
        if (
            len(accepted) < settings.idea_generator_result_count
            and settings.idea_generator_max_synthesis_attempts > 1
        ):
            missing = settings.idea_generator_result_count - len(accepted)
            repair_system_prompt = (
                load_prompt("idea_generator_shared").format(
                    candidate_count=missing,
                    result_count=missing,
                )
                + "\n\n"
                + load_prompt(format_prompt_name)
            )
            existing_titles = [item.candidate.title for item in accepted]
            repair_human = (
                f"Create exactly {missing} replacement candidate(s).\n"
                f"Do not repeat these accepted titles: {json.dumps(existing_titles)}.\n"
                f"Previous validation failures: {json.dumps(rejected)}.\n\n"
                "Use only these compact factual references:\n"
                f"{_source_digest(sources, limit=20, excerpt_chars=400)}\n\n"
                "VIDIQ SIGNALS:\n"
                f"{_signal_digest(signals, limit=15) or '(vidIQ unavailable)'}"
            )
            # Repair is a top-up, never the thing that breaks a run. If either
            # ceiling is too tight for it, ship what validation already
            # accepted and say why in the metrics.
            repair_time = deadline.allot(settings.idea_generator_repair_timeout_seconds)
            repair_affordable = ledger.affords(
                model=settings.claude_model,
                input_tokens=estimate_tokens(repair_system_prompt + repair_human),
                max_output_tokens=settings.idea_generator_repair_max_tokens,
            )
            if not repair_affordable:
                log.warning(
                    "idea_generator.repair_skipped_budget",
                    remaining_usd=round(ledger.remaining_usd, 4),
                )
                rejected["repair_skipped_budget"] = rejected.get("repair_skipped_budget", 0) + 1
            elif repair_time < 5:
                log.warning("idea_generator.repair_skipped_deadline", remaining_seconds=round(repair_time, 1))
                rejected["repair_skipped_deadline"] = rejected.get("repair_skipped_deadline", 0) + 1
            else:
                try:
                    synthesis_calls += 1
                    repair = await _bounded(
                        self._repair_structured_llm.ainvoke(
                            [
                                SystemMessage(content=repair_system_prompt),
                                HumanMessage(content=repair_human),
                            ],
                            config=ledger_config("repair"),
                        ),
                        timeout=repair_time,
                        error_code="repair_timed_out",
                    )
                    accept_candidates(repair.candidates)
                except RuntimeError as exc:
                    if str(exc) != "repair_timed_out" or not accepted:
                        raise
                    rejected["repair_timed_out"] = rejected.get("repair_timed_out", 0) + 1

        if not accepted:
            raise RuntimeError("insufficient_evidence")
        if on_stage is not None:
            await on_stage("validating_and_ranking_ideas", 82)

        # Distinctness is a hard requirement, not a ranking preference. The
        # previous pass preferred one idea per sector and then back-filled the
        # remaining slots from any accepted candidate, so two ideas from the same
        # sector — or two angles on the same company — could still ship together.
        accepted.sort(key=lambda item: item.score, reverse=True)
        selected: list[ScoredIdea] = []
        seen_sectors: set[str] = set()
        for idea in accepted:
            if len(selected) == settings.idea_generator_result_count:
                break
            sector = idea.candidate.sector.strip().casefold()
            if sector in seen_sectors:
                rejected["duplicate_sector"] = rejected.get("duplicate_sector", 0) + 1
                continue
            if any(_same_subject(idea.candidate, chosen.candidate) for chosen in selected):
                rejected["duplicate_subject"] = rejected.get("duplicate_subject", 0) + 1
                continue
            selected.append(idea)
            seen_sectors.add(sector)

        for rank, idea in enumerate(selected, start=1):
            idea.rank = rank

        provider_statuses = {
            "research": {
                "status": "complete",
                "detail": "Multi-source web, news, RSS and financial research completed.",
                "evidence_count": len(sources),
            },
            "deep_research": {
                "status": "complete" if package.deep_research_report else "unavailable",
                "detail": "Anthropic deep research contributed evidence." if package.deep_research_report else "No deep-research report was returned.",
                "evidence_count": package.deep_research_web_search_requests,
            },
            "vidiq": {
                "status": "partial" if vidiq_raw and vidiq_raw.get("partial") else "complete" if vidiq_raw else "unavailable",
                "detail": (
                    f"{len(signals)} YouTube trend signals collected."
                    if vidiq_raw
                    else "vidIQ did not return data."
                ),
                "evidence_count": len(signals),
            },
            "google_trends": {
                "status": "not_configured",
                "detail": "Google Trends is intentionally not implemented in V2.",
                "evidence_count": 0,
            },
        }
        coverage_reasons = ["google_trends_not_configured"]
        if not vidiq_raw:
            coverage_reasons.append("vidiq_unavailable")
        if len(selected) < settings.idea_generator_result_count:
            coverage_reasons.append("partial_idea_count")
        return IdeaGenerationResult(
            ideas=selected,
            sources=sources,
            signals=signals,
            provider_statuses=provider_statuses,
            coverage_reasons=coverage_reasons,
            candidate_metrics={
                "accepted": len(accepted),
                "selected": len(selected),
                "rejected": rejected,
            },
            usage_metrics={
                "synthesis_calls": synthesis_calls,
                "vidiq_credits_spent": int((vidiq_raw or {}).get("credits_spent") or 0),
                "deep_research_web_search_requests": package.deep_research_web_search_requests,
                **ledger.snapshot(),
            },
        )


__all__ = [
    "IdeaGeneratorAgent",
    "IdeaGenerationResult",
    "IdeaCandidate",
    "CandidateSet",
    "_score_candidate",
]
