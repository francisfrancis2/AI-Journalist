"""
Anthropic-powered web search tool.

Uses Claude's built-in `web_search_20250305` server tool to run agentic
search. Claude can chain multiple searches in a single call (e.g. follow
up on a term it spotted in the first results), which Tavily can't do.

This tool runs **in parallel** with TavilySearchTool inside the Researcher.
Both feed the same ResearchPackage, so the analyst gets the union of URLs
from two different search engines (Tavily uses Bing/Google, Anthropic
uses Brave).

Results are returned as RawSource objects identical in shape to what
TavilySearchTool produces, with `metadata.provider == "anthropic_search"`
so downstream consumers and any future A/B analysis can tell the sources
apart.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import structlog
from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import settings
from backend.models.research import RawSource, SourceCredibility, SourceType

log = structlog.get_logger(__name__)


# Shared credibility heuristic — duplicated tiny lists rather than importing
# from web_search.py to keep the two tools independent.
_HIGH_CREDIBILITY_DOMAINS = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com",
    "apnews.com", "bbc.com", "nytimes.com", "theguardian.com",
    "cnbc.com", "forbes.com", "economist.com",
}
_MEDIUM_CREDIBILITY_DOMAINS = {
    "techcrunch.com", "wired.com", "businessinsider.com",
    "axios.com", "politico.com", "theatlantic.com",
}


def _infer_credibility(url: Optional[str]) -> SourceCredibility:
    if not url:
        return SourceCredibility.LOW
    domain = url.split("/")[2].replace("www.", "") if "//" in url else ""
    if domain in _HIGH_CREDIBILITY_DOMAINS:
        return SourceCredibility.HIGH
    if domain in _MEDIUM_CREDIBILITY_DOMAINS:
        return SourceCredibility.MEDIUM
    return SourceCredibility.LOW


def _strip_code_fence(text: str) -> str:
    """Strip ``` or ```json fences if the model wrapped the JSON."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    # Drop first line (```) and trailing closing fence
    parts = stripped.split("\n", 1)
    if len(parts) == 2:
        body = parts[1]
    else:
        body = ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3]
    return body.strip()


def _extract_search_results_from_blocks(content_blocks: list[Any]) -> list[dict]:
    """
    Fallback parser: when the model didn't return JSON, harvest URLs/titles
    straight from web_search_tool_result content blocks.
    """
    out: list[dict] = []
    for block in content_blocks:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        inner = getattr(block, "content", []) or []
        for r in inner:
            if getattr(r, "type", None) != "web_search_result":
                continue
            url = getattr(r, "url", None)
            if not url:
                continue
            out.append({
                "title": getattr(r, "title", None) or "(untitled)",
                "url": url,
                "snippet": "",
                "page_age": getattr(r, "page_age", None),
            })
    return out


_QUERY_PROMPT = (
    "Search the web for: {query}\n\n"
    "Use up to {max_uses} search calls. Chain follow-up searches if early "
    "results surface a more specific term worth pursuing.\n\n"
    "After you have searched, respond with a JSON block in EXACTLY this shape:\n"
    "{{\"results\": [{{\"title\": \"...\", \"url\": \"...\", \"snippet\": \"1-2 sentence summary\"}}]}}\n\n"
    "List up to 10 of the most relevant sources you found. Do not include any "
    "text outside the JSON block."
)


class AnthropicSearchTool:
    """
    Anthropic server-side web search wrapper.

    Mirrors the WebSearchTool interface (`search` + `multi_search`) so it
    can be dropped into the Researcher's parallel gather block as a peer.
    """

    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        # Haiku is the cheapest model that supports the web_search tool —
        # we only need it to dispatch + format, not to reason deeply.
        self._model = settings.claude_haiku_model
        self._max_uses_per_query = settings.anthropic_search_max_uses_per_query

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=8))
    async def _call_once(self, query: str) -> list[dict]:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": self._max_uses_per_query,
                }],
                messages=[{
                    "role": "user",
                    "content": _QUERY_PROMPT.format(
                        query=query,
                        max_uses=self._max_uses_per_query,
                    ),
                }],
            )
        except Exception as exc:
            log.warning("anthropic_search.api_error", query=query, error=str(exc))
            raise

        # Concatenate all text blocks (the model may emit text between searches)
        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")
        text = "\n".join(text_parts).strip()

        if text:
            try:
                payload = json.loads(_strip_code_fence(text))
                results = payload.get("results") if isinstance(payload, dict) else None
                if isinstance(results, list):
                    return [r for r in results if isinstance(r, dict) and r.get("url")]
            except (json.JSONDecodeError, TypeError):
                log.debug("anthropic_search.json_parse_failed", query=query)

        # JSON path failed — fall back to harvesting URLs from the raw
        # web_search_tool_result blocks so we still get something useful.
        return _extract_search_results_from_blocks(response.content)

    async def search(self, query: str) -> list[RawSource]:
        try:
            raw = await self._call_once(query)
        except Exception as exc:
            log.warning("anthropic_search.failed", query=query, error=str(exc))
            return []

        sources: list[RawSource] = []
        for r in raw:
            url = r.get("url")
            if not url:
                continue
            sources.append(
                RawSource(
                    source_type=SourceType.WEB_SEARCH,
                    url=url,
                    title=r.get("title") or "(untitled)",
                    content=r.get("snippet") or "",
                    relevance_score=0.55,  # neutral — analyst will re-rank
                    credibility=_infer_credibility(url),
                    metadata={
                        "provider": "anthropic_search",
                        "published_date": r.get("page_age"),
                    },
                )
            )
        log.info("anthropic_search.complete", query=query, results_count=len(sources))
        return sources

    async def multi_search(
        self,
        queries: list[str],
        max_results_per_query: int = 10,  # accepted for interface parity; unused
    ) -> list[RawSource]:
        """Run multiple queries concurrently and deduplicate by URL."""
        if not queries:
            return []

        results_nested = await asyncio.gather(
            *[self.search(q) for q in queries],
            return_exceptions=True,
        )

        seen_urls: set[str] = set()
        all_sources: list[RawSource] = []
        for batch in results_nested:
            if isinstance(batch, Exception):
                log.warning("anthropic_search.query_failed", error=str(batch))
                continue
            for src in batch:
                if src.url and src.url not in seen_urls:
                    seen_urls.add(src.url)
                    all_sources.append(src)
        log.info(
            "anthropic_search.multi_complete",
            queries=len(queries),
            unique_results=len(all_sources),
        )
        return all_sources
