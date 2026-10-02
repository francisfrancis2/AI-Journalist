"""
vidIQ MCP integration — YouTube audience-demand signal for the research pipeline.

Speaks MCP Streamable HTTP (JSON-RPC 2.0) directly over httpx so no new runtime
dependency is introduced. The protocol surface we need is small: initialize, then
tools/call.

Two tools are used, both billed at ~5 vidIQ credits per call:
  vidiq_keyword_research  — search volume / competition for a seed + related terms
  vidiq_youtube_search    — top videos per keyword (order=relevance, duration-banded)

Design rules:
  - FAIL OPEN. Every public entry point returns None/partial rather than raising.
    vidIQ is an enrichment; credit exhaustion must degrade quality, never fail a story.
  - BUDGETED. settings.vidiq_max_calls_per_story caps spend per pipeline run.
  - CACHED. Keyword demand moves weekly, so identical calls are served from an
    in-process TTL cache; repeat topics cost nothing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import date, timedelta
from typing import Any, Optional

import httpx
import structlog

from backend.config import settings
from backend.models.research import (
    RawSource,
    SourceCredibility,
    SourceType,
    YouTubeDemandReport,
    YouTubeKeyword,
    YouTubeVideo,
)

log = structlog.get_logger(__name__)

MCP_URL = "https://mcp.vidiq.com/mcp"
PROTOCOL_VERSION = "2025-06-18"
KEYWORD_TOOL = "vidiq_keyword_research"
VIDEO_TOOL = "vidiq_youtube_search"
TRENDING_TOOL = "vidiq_trending_videos"
OUTLIERS_TOOL = "vidiq_outliers"

# ── relevance filtering (topic-agnostic) ──────────────────────────────────────
# The topic vocabulary is derived from vidIQ's own related keywords, so nothing
# here is subject-specific. Only entertainment markers are fixed, because those
# describe format rather than topic.

_STOP = {"the", "and", "for", "you", "your", "how", "why", "what", "best", "top",
         "new", "with", "this", "that", "from", "get", "make", "can", "are", "was",
         "has", "its", "all", "out", "about", "video", "videos", "youtube", "full"}

_ENTERTAINMENT_RE = re.compile(
    r"(episode\s*[\d|]|full movie|prank|fortnite|minecraft|gameplay|simulator|"
    r"\bsong\b|cartoons?|kids tv|\bvlog\b|unboxing|giveaway|reaction|"
    r"try not to|challenge\s*!|\bskit\b|\bmeme|"
    r"top\s*\d+\s*best|\btemu\b|buying guide|\bdeals?\b|discount code|"
    r"\#\d+|part\s*\d+\b)", re.I)
_MILITARY_RE = re.compile(
    r"\b(strike|attack|war|weapon|missile|combat|military|kamikaze|fpv|ukrain\w*|"
    r"russia\w*)\b", re.I)


def _stems(text: str, n: int = 5) -> set[str]:
    """Prefix stems so 'delivery'/'deliveries' and 'drone'/'drones' unify."""
    return {w[:n] for w in re.findall(r"[a-z]{3,}", (text or "").lower())
            if w not in _STOP}


def _iso_to_seconds(iso: Optional[str]) -> int:
    if not iso:
        return 0
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not match:
        return 0
    hours, mins, secs = (int(x) if x else 0 for x in match.groups())
    return hours * 3600 + mins * 60 + secs


def _extract_embedded_json(payload: Any) -> Any:
    """vidIQ answers LLM-first: markdown prose with a JSON block appended."""
    if not isinstance(payload, str):
        return payload
    for opener, closer in (("{", "}"), ("[", "]")):
        start = payload.find(opener)
        while start != -1:
            depth, in_str, escaped = 0, False, False
            for i in range(start, len(payload)):
                ch = payload[i]
                if in_str:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(payload[start:i + 1])
                        except ValueError:
                            break
            start = payload.find(opener, start + 1)
    return None


# ── in-process TTL cache ──────────────────────────────────────────────────────

_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_key(tool: str, args: dict) -> str:
    blob = json.dumps({"t": tool, "a": args}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _cache_get(key: str) -> Any:
    hit = _CACHE.get(key)
    if not hit:
        return None
    cached_at, value = hit
    if time.time() - cached_at > settings.vidiq_cache_ttl_seconds:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    if len(_CACHE) > 512:                       # crude bound; this is a hot-path cache
        _CACHE.clear()
    _CACHE[key] = (time.time(), value)


def _video_search_keywords(keywords: list[YouTubeKeyword], seed_stems: set[str],
                           limit: int) -> list[YouTubeKeyword]:
    """Pick which related keywords also get a video search.

    NOT simply the highest-volume ones. The top terms by volume are broad head
    terms ("drone", "drones", "logistics") whose best-performing videos are
    consumer product roundups, not subject-matter programming. Specificity is
    what makes the video set usable, so rank by: overlap with the seed first,
    then multi-word terms, then volume.
    """
    candidates = []
    for kw in keywords:
        stems = _stems(kw.keyword)
        overlap = len(stems & seed_stems)
        if not overlap:
            continue                               # unrelated head term, e.g. "logistics"
        words = len(kw.keyword.split())
        if words < 2:
            continue                               # the bare subject noun is too broad
        candidates.append((overlap, words > 1, kw.estimated_monthly_search, kw))
    candidates.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    picked = [row[3] for row in candidates[:limit]]
    # Fall back to plain volume order only if nothing specific qualified.
    return picked or keywords[:limit]


class VidIQTool:
    """Async vidIQ MCP client returning a YouTubeDemandReport. Never raises."""

    def __init__(self) -> None:
        self._api_key = settings.vidiq_api_key
        self._calls_made = 0

    @property
    def enabled(self) -> bool:
        return bool(settings.enable_vidiq and self._api_key)

    # ── MCP plumbing ──────────────────────────────────────────────────────────

    async def _call_tool(self, client: httpx.AsyncClient, session_id: Optional[str],
                         tool: str, args: dict) -> tuple[Any, Optional[str]]:
        """One tools/call. Returns (payload, session_id). Cached calls are free."""
        key = _cache_key(tool, args)
        cached = _cache_get(key)
        if cached is not None:
            log.info("vidiq.cache_hit", tool=tool)
            return cached, session_id

        if self._calls_made >= settings.vidiq_max_calls_per_story:
            log.warning("vidiq.budget_exhausted", tool=tool,
                        cap=settings.vidiq_max_calls_per_story)
            return None, session_id

        headers = {"Mcp-Session-Id": session_id} if session_id else {}
        body = {"jsonrpc": "2.0", "id": self._calls_made + 2, "method": "tools/call",
                "params": {"name": tool, "arguments": args}}
        resp = await client.post(MCP_URL, json=body, headers=headers)
        session_id = resp.headers.get("mcp-session-id") or session_id
        if resp.status_code >= 400:
            log.warning("vidiq.http_error", tool=tool, status=resp.status_code)
            return None, session_id

        envelope = self._parse(resp)
        self._calls_made += 1
        if "error" in envelope:
            log.warning("vidiq.rpc_error", tool=tool, error=str(envelope["error"])[:200])
            return None, session_id

        result = envelope.get("result") or {}
        if result.get("isError"):
            log.warning("vidiq.tool_error", tool=tool)
            return None, session_id

        payload = result.get("structuredContent")
        if not payload:
            for block in result.get("content") or []:
                if block.get("type") == "text":
                    payload = _extract_embedded_json(block.get("text", ""))
                    break
        if payload is not None:
            _cache_set(key, payload)
        return payload, session_id

    @staticmethod
    def _parse(resp: httpx.Response) -> dict:
        if "text/event-stream" in resp.headers.get("content-type", ""):
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    parsed = json.loads(line[5:].strip())
                    if "result" in parsed or "error" in parsed:
                        return parsed
            return {}
        return json.loads(resp.text) if resp.text.strip() else {}

    # ── public API ────────────────────────────────────────────────────────────

    async def fetch_demand_report(
        self, topic: str, search_seed: Optional[str] = None,
    ) -> Optional[YouTubeDemandReport]:
        """Keyword demand + top long-form videos for a topic. None on any failure."""
        if not self.enabled:
            return None

        seed = (search_seed or topic).strip()
        self._calls_made = 0
        try:
            async with httpx.AsyncClient(
                timeout=settings.vidiq_timeout_seconds,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            ) as client:
                return await asyncio.wait_for(
                    self._build_report(client, topic, seed),
                    timeout=settings.vidiq_total_timeout_seconds,
                )
        except asyncio.TimeoutError:
            log.warning("vidiq.timeout", topic=topic[:80])
        except Exception as exc:                       # fail open, always
            log.warning("vidiq.failed", topic=topic[:80], error=str(exc)[:200])
        return None

    async def fetch_idea_trends(self, *, window_days: int = 30) -> Optional[dict[str, Any]]:
        """Collect broad YouTube opportunity signals for UAE business ideation.

        Country keyword volume is an in-country demand estimate. Trending and
        outlier country filters describe where the publishing channel is based,
        not where its audience lives; that distinction is preserved in the
        returned payload and must not be upgraded into an audience claim.
        """
        if not self.enabled:
            return None

        self._calls_made = 0
        since = (date.today() - timedelta(days=max(1, window_days))).isoformat()
        try:
            async with httpx.AsyncClient(
                timeout=settings.vidiq_timeout_seconds,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            ) as client:
                return await asyncio.wait_for(
                    self._build_idea_trends(client, since=since, window_days=window_days),
                    timeout=settings.vidiq_total_timeout_seconds,
                )
        except asyncio.TimeoutError:
            log.warning("vidiq.idea_trends_timeout")
        except Exception as exc:
            log.warning("vidiq.idea_trends_failed", error=str(exc)[:200])
        return None

    async def _initialize(self, client: httpx.AsyncClient) -> tuple[bool, Optional[str]]:
        """Open an MCP session. Returns (ok, session_id).

        The two are separate signals and must not be conflated: vidIQ's server
        does NOT return an Mcp-Session-Id header, so a successful handshake
        yields session_id=None. Returning the bare session id made every caller
        read that as an initialisation failure and abandon the request before
        issuing a single tools/call — which is why YouTube demand silently came
        back empty for every story.
        """
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ai-journalist", "version": "2.0"},
            },
        }
        resp = await client.post(MCP_URL, json=init)
        if resp.status_code >= 400:
            log.warning("vidiq.init_failed", status=resp.status_code)
            return False, None
        session_id = resp.headers.get("mcp-session-id")
        await client.post(
            MCP_URL,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={"Mcp-Session-Id": session_id} if session_id else {},
        )
        return True, session_id

    async def _build_idea_trends(
        self, client: httpx.AsyncClient, *, since: str, window_days: int
    ) -> Optional[dict[str, Any]]:
        ok, session_id = await self._initialize(client)
        if not ok:
            return None

        calls = [
            (
                "uae_country_keywords",
                KEYWORD_TOOL,
                {
                    "mode": "country_search",
                    "keyword": "business economy technology entrepreneurship",
                    "country": "AE",
                    "broad": True,
                    "limit": 30,
                },
                "United Arab Emirates search volume",
            ),
            (
                "global_rising_keywords",
                KEYWORD_TOOL,
                {"mode": "rising", "period": "month", "language": "en", "limit": 30},
                "Global YouTube keyword momentum; not UAE-specific",
            ),
            (
                "uae_channel_trending_videos",
                TRENDING_TOOL,
                {
                    "videoFormat": "long",
                    "titleQuery": "UAE business economy technology entrepreneurship",
                    "channelCountry": "AE",
                    "videoTitleLanguage": "en",
                    "videoPublishedAfter": since,
                    "sortBy": "vph",
                    "limit": 20,
                },
                "Channels based in UAE; not UAE audience geography",
            ),
            (
                "uae_channel_outliers",
                OUTLIERS_TOOL,
                {
                    "keyword": "UAE business economy technology entrepreneurship",
                    "contentType": "long",
                    "publishedWithin": "thisMonth" if window_days <= 31 else "threeMonths",
                    "channelCountry": "AE",
                    "language": "en",
                    "sort": "breakoutScore",
                    "limit": 20,
                },
                "Channels based in UAE; not UAE audience geography",
            ),
        ]

        payloads: dict[str, Any] = {}
        semantics: dict[str, str] = {}
        for key, tool, args, geography_meaning in calls:
            payload, session_id = await self._call_tool(client, session_id, tool, args)
            if payload is not None:
                payloads[key] = payload
                semantics[key] = geography_meaning

        if not payloads:
            return None
        return {
            "window_days": window_days,
            "geography": "AE",
            "payloads": payloads,
            "geography_semantics": semantics,
            "credits_spent": self._calls_made * 5,
            "partial": len(payloads) < len(calls),
        }

    async def _build_report(self, client: httpx.AsyncClient, topic: str,
                            seed: str) -> Optional[YouTubeDemandReport]:
        ok, session_id = await self._initialize(client)
        if not ok:
            return None

        kw_payload, session_id = await self._call_tool(
            client, session_id, KEYWORD_TOOL,
            {"mode": "research", "keyword": seed, "includeRelated": True})
        if not isinstance(kw_payload, dict):
            return None

        seed_kw = self._to_keyword(kw_payload.get("seedKeyword") or {})
        keywords = [k for k in (self._to_keyword(row)
                                for row in kw_payload.get("relatedKeywords") or [])
                    if k and k.estimated_monthly_search > 0]
        keywords.sort(key=lambda k: k.estimated_monthly_search, reverse=True)

        vocabulary = set(_stems(seed))
        for kw in keywords:
            vocabulary |= _stems(kw.keyword)
        seed_stems = _stems(seed)

        # Query the seed plus the highest-demand related terms, across both
        # duration bands, so 4-minute explainers and 40-minute documentaries
        # both surface.
        queries = [seed] + [
            k.keyword for k in _video_search_keywords(
                keywords, seed_stems, settings.vidiq_keyword_fanout)
        ]
        videos: dict[str, YouTubeVideo] = {}
        for query in queries:
            for band in ("long", "medium"):
                if self._calls_made >= settings.vidiq_max_calls_per_story:
                    break
                payload, session_id = await self._call_tool(
                    client, session_id, VIDEO_TOOL,
                    {"query": query, "order": "relevance", "type": ["video"],
                     "limit": 10, "videoDuration": band})
                for row in ((payload or {}).get("results") or []):
                    video = self._to_video(row, query)
                    if video and self._on_topic(video, vocabulary, seed_stems):
                        videos.setdefault(video.video_id, video)

        ranked = sorted(videos.values(), key=lambda v: v.view_count, reverse=True)
        report = YouTubeDemandReport(
            topic=topic, search_seed=seed, seed_keyword=seed_kw,
            keywords=keywords[: settings.vidiq_max_keywords],
            videos=ranked[: settings.vidiq_max_videos],
            credits_spent=self._calls_made * 5,
            partial=self._calls_made >= settings.vidiq_max_calls_per_story,
        )
        log.info("vidiq.report_built", topic=topic[:80], keywords=len(report.keywords),
                 videos=len(report.videos), calls=self._calls_made)
        return report

    # ── mapping ───────────────────────────────────────────────────────────────

    @staticmethod
    def _on_topic(video: YouTubeVideo, vocabulary: set[str], seed_stems: set[str]) -> bool:
        """Title must carry >=2 topic stems including one from the seed.

        Title-only on purpose: descriptions mention anything in passing, so
        matching them lets unrelated content through on a single stray word.
        """
        title = video.title or ""
        if _ENTERTAINMENT_RE.search(title) or _MILITARY_RE.search(title):
            return False
        if video.duration_seconds < settings.vidiq_min_video_seconds:
            return False
        title_stems = _stems(title)
        return len(title_stems & vocabulary) >= 2 and bool(title_stems & seed_stems)

    @staticmethod
    def _to_keyword(row: dict) -> Optional[YouTubeKeyword]:
        if not isinstance(row, dict) or not row.get("keyword"):
            return None
        return YouTubeKeyword(
            keyword=str(row["keyword"]),
            volume=float(row.get("volume") or 0),
            competition=row.get("competition"),
            overall=row.get("overall"),
            estimated_monthly_search=int(row.get("estimatedMonthlySearch") or 0),
            monthly_display=str(row.get("monthlySearchesDisplay") or ""),
            label=str(row.get("volumeScoreLabel") or ""),
        )

    @staticmethod
    def _to_video(row: dict, query: str) -> Optional[YouTubeVideo]:
        if not isinstance(row, dict) or row.get("kind") != "video" or not row.get("id"):
            return None
        return YouTubeVideo(
            video_id=str(row["id"]),
            title=str(row.get("title") or ""),
            channel=row.get("channelTitle"),
            view_count=int(row.get("viewCount") or 0),
            duration_seconds=_iso_to_seconds(row.get("duration")),
            published_at=(row.get("publishedAt") or "")[:10] or None,
            matched_keyword=query,
        )


def demand_report_to_sources(report: YouTubeDemandReport) -> list[RawSource]:
    """Expose top videos as RawSource so they flow through the existing package."""
    sources: list[RawSource] = []
    for video in report.videos:
        sources.append(RawSource(
            source_type=SourceType.YOUTUBE_BENCHMARK,
            title=video.title,
            url=video.url,
            content=(
                f"YouTube audience-demand benchmark. "
                f"{video.view_count:,} views, {video.duration_display} long, "
                f"channel {video.channel or 'unknown'}, published {video.published_at or 'unknown'}. "
                f"Surfaced for keyword '{video.matched_keyword}'."
            ),
            credibility=SourceCredibility.MEDIUM,
        ))
    return sources
