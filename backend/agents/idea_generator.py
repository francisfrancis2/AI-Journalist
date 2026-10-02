"""Evidence-first UAE business idea generation agent (V2)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from backend.agents.research import ResearchAgent
from backend.config import settings
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
    sector: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=8, max_length=220)
    premise: str = Field(min_length=30, max_length=1200)
    why_now: str = Field(min_length=20, max_length=900)
    uae_relevance: str = Field(min_length=20, max_length=900)
    central_tension: str = Field(min_length=15, max_length=700)
    target_audience: str = Field(min_length=5, max_length=300)
    business_significance: str = Field(min_length=20, max_length=900)
    format_details: dict[str, Any]
    source_ids: list[str] = Field(min_length=2, max_length=8)
    signal_keys: list[str] = Field(default_factory=list, max_length=8)
    verification_gaps: list[str] = Field(default_factory=list, max_length=6)


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
    confidence: float
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


def _prepare_signals(raw: dict[str, Any] | None) -> list[PreparedSignal]:
    if not raw:
        return []
    signals: list[PreparedSignal] = []
    semantics = raw.get("geography_semantics") or {}
    for group, payload in (raw.get("payloads") or {}).items():
        for index, (path, row) in enumerate(_walk_rows(payload)):
            if len(signals) >= 60:
                break
            topic = str(
                row.get("keyword")
                or row.get("title")
                or row.get("question")
                or row.get("name")
                or "YouTube opportunity signal"
            )
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
                else "growth" if group == "global_rising_keywords"
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
                    geography="AE" if group != "global_rising_keywords" else None,
                    geography_meaning=semantics.get(group),
                    observed_at=datetime.now(timezone.utc),
                    window_days=int(raw.get("window_days") or 30),
                    metric=metric,
                    values=_safe_json(row),
                    source_url=row.get("url") or row.get("videoUrl"),
                    domain="youtube.com" if "video" in group or "outlier" in group else None,
                    reliability="medium",
                    raw_reference={"group": group, "path": path},
                )
            )
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
    if len(sources) < 2 or len(domains) < 2:
        return None, "fewer_than_two_independent_domains"
    if not any(_is_current_uae_source(source) for source in sources):
        return None, "missing_current_reliable_uae_source"
    if _policy_conflict(candidate):
        return None, "editorial_policy_conflict"

    uae = min(20.0, 12.0 + 2.0 * sum(source.is_uae_relevant for source in sources))
    timeliness = min(20.0, 10.0 + 3.0 * sum(_is_current_uae_source(source) for source in sources))
    youtube = min(15.0, 5.0 + 2.5 * len(signals)) if signals else 3.0
    significance = min(15.0, 8.0 + len(candidate.business_significance) / 180.0 + len(sources))
    editorial = min(15.0, 8.0 + len(candidate.central_tension) / 120.0 + len(candidate.format_details))
    feasibility = min(10.0, 5.0 + len(candidate.format_details))
    evidence = min(5.0, 1.0 + len(domains) + 0.5 * sum(source.credibility == "high" for source in sources))
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
    confidence = min(0.95, round(0.48 + 0.06 * len(domains) + 0.03 * len(signals), 2))
    strength = "strong" if total >= 80 else "promising" if total >= 65 else "developing"
    return (
        ScoredIdea(
            candidate=candidate,
            score_breakdown=breakdown,
            score=total,
            strength=strength,
            confidence=confidence,
            source_ids=[source.id for source in sources],
            signal_ids=[signal.id for signal in signals],
        ),
        None,
    )


def _source_digest(sources: list[PreparedSource]) -> str:
    rows = []
    for source in sources[:40]:
        rows.append(
            f"SOURCE_ID={source.reference_id}\nTitle: {source.title}\n"
            f"Domain: {source.domain or 'unknown'} | Published: {source.published_at or 'unknown'} | "
            f"Credibility: {source.credibility} | UAE-relevant: {source.is_uae_relevant}\n"
            f"Evidence: {source.excerpt[:650]}"
        )
    return "\n\n".join(rows)


def _signal_digest(signals: list[PreparedSignal]) -> str:
    return "\n".join(
        f"SIGNAL_KEY={signal.key} | {signal.signal_type} | {signal.topic} | "
        f"Geography meaning: {signal.geography_meaning or 'not geographic'} | "
        f"Values: {json.dumps(signal.values, default=str)[:450]}"
        for signal in signals[:35]
    )



async def _bounded(awaitable):
    """Fail the research phase loudly rather than letting the watchdog sweep it.

    Without a bound, a slow deep-research pass runs past the watchdog's 30-minute
    staleness threshold and the run is marked failed with a generic "interrupted"
    message that says nothing about the cause.
    """
    try:
        return await asyncio.wait_for(
            awaitable, timeout=settings.idea_generator_research_timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError("research_timed_out") from exc


class IdeaGeneratorAgent:
    """Researches, verifies, ranks, and returns exactly five supported ideas."""

    def __init__(self) -> None:
        # Claude Opus 4.7 is a reasoning model: `temperature` was removed from
        # its API and sending it returns 400 invalid_request_error. Every other
        # agent here already omits it on Opus; this one was missed, which failed
        # every generation with "Idea generation could not complete."
        # max_tokens must fit the whole CandidateSet in one response. At
        # idea_generator_candidate_count=8, the schema's text fields alone can
        # reach ~10.5k tokens before JSON overhead; the previous 7000 ceiling
        # truncated the model mid-tool-call, so LangChain received empty tool
        # arguments and every run died on "1 validation error for CandidateSet:
        # candidates Field required [input_value={}]".
        llm = ChatAnthropic(
            model=settings.claude_opus_model,
            api_key=settings.anthropic_api_key,
            max_tokens=16000,
        )
        self._structured_llm = llm.with_structured_output(CandidateSet)
        self._research = ResearchAgent()

    async def generate(self, idea_format: IdeaFormat) -> IdeaGenerationResult:
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
        package, vidiq_raw = await _bounded(asyncio.gather(
            self._research.gather_package(
                prompt=research_prompt,
                deep=True,
                include_vidiq=False,
                rss_country="AE",
                # Deliberately NOT capped to the lighter pipeline budget. Doing
                # so starved the evidence set: generate() requires >=2 distinct
                # source domains and a reduced search budget tripped
                # "insufficient_evidence". The watchdog problem this was meant
                # to solve is handled by the wall-clock bound in _bounded()
                # instead, which is the right lever for a time limit.
            ),
            VidIQTool().fetch_idea_trends(window_days=30),
        ))
        sources = _prepare_sources(package)
        signals = _prepare_signals(vidiq_raw)
        if len({source.domain for source in sources if source.domain}) < 2:
            raise RuntimeError("insufficient_evidence")

        source_map = {source.reference_id: source for source in sources}
        signal_map = {signal.key: signal for signal in signals}
        rejected: dict[str, int] = {}
        accepted: list[ScoredIdea] = []
        synthesis_calls = 0

        system_prompt = (
            "You are the Idea Generator V2 producer-agent for a UAE business video newsroom. "
            f"Return up to {settings.idea_generator_candidate_count} distinct {format_label} candidates. "
            "Every factual claim must be grounded in the supplied sources. Each candidate must cite at "
            "least two SOURCE_IDs from different independent domains, including one current reliable "
            "UAE-relevant source. Use vidIQ only as YouTube opportunity evidence; never treat it as factual "
            "corroboration and never claim channelCountry proves UAE audience location. Do not invent facts, "
            "experts, access, metrics, or source IDs. Return only the requested idea fields. Keep UAE "
            "government, rulers, and institutions "
            "neutral or constructive. If truthful use of a topic conflicts with that policy, omit the topic "
            "rather than sanitizing its evidence. Ensure sector diversity. For documentary ideas, format_details "
            "should contain protagonist_or_system, access_path, visual_world, and story_arc. For expert interviews, "
            "it should contain expert_profile, interview_thesis, key_questions, and visual_support."
        )

        for attempt in range(settings.idea_generator_max_synthesis_attempts):
            synthesis_calls += 1
            recovery = (
                f"\nPrevious validation rejected candidates for: {json.dumps(rejected)}. Replace them with "
                "better-supported, genuinely distinct candidates using only the supplied evidence."
                if attempt and rejected
                else ""
            )
            result = await self._structured_llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(
                        content=(
                            f"Today is {datetime.now(timezone.utc).date().isoformat()}.\n"
                            f"Requested format: {idea_format.value}.\n\nFACTUAL SOURCES:\n{_source_digest(sources)}\n\n"
                            f"VIDIQ OPPORTUNITY SIGNALS:\n{_signal_digest(signals) or '(vidIQ unavailable)'}"
                            f"{recovery}"
                        )
                    ),
                ]
            )
            for candidate in result.candidates:
                if any(existing.candidate.title.casefold() == candidate.title.casefold() for existing in accepted):
                    rejected["duplicate_title"] = rejected.get("duplicate_title", 0) + 1
                    continue
                scored, reason = _score_candidate(candidate, source_map, signal_map)
                if scored is None:
                    rejected[reason or "validation_failed"] = rejected.get(reason or "validation_failed", 0) + 1
                    continue
                accepted.append(scored)
            if len(accepted) >= settings.idea_generator_result_count:
                break

        # Diversity-aware deterministic ranking: score first, with only one item
        # per sector before filling remaining slots.
        accepted.sort(key=lambda item: item.score, reverse=True)
        selected: list[ScoredIdea] = []
        seen_sectors: set[str] = set()
        for idea in accepted:
            sector = idea.candidate.sector.strip().casefold()
            if sector not in seen_sectors:
                selected.append(idea)
                seen_sectors.add(sector)
            if len(selected) == settings.idea_generator_result_count:
                break
        for idea in accepted:
            if len(selected) == settings.idea_generator_result_count:
                break
            if idea not in selected:
                selected.append(idea)
        if len(selected) != settings.idea_generator_result_count:
            # Carry the rejection tally into the error. Without it the failure
            # reads as "insufficient_evidence" with no way to tell whether
            # research was thin, the model produced duplicates, or verification
            # rejected everything — three very different problems.
            log.warning(
                "idea_generator.insufficient_after_verification",
                selected=len(selected),
                required=settings.idea_generator_result_count,
                accepted=len(accepted),
                rejected=rejected,
                sources=len(sources),
                domains=len({s.domain for s in sources if s.domain}),
            )
            raise RuntimeError("insufficient_evidence")
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
                "detail": "YouTube demand and video opportunity signals collected." if vidiq_raw else "vidIQ did not return data.",
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
            },
        )


__all__ = [
    "IdeaGeneratorAgent",
    "IdeaGenerationResult",
    "IdeaCandidate",
    "CandidateSet",
    "_score_candidate",
]
