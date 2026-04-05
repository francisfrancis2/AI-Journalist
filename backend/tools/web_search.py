"""
Tavily-powered web search tool.
Returns structured search results that the Researcher agent can consume directly.
"""

import asyncio
from typing import Any, Optional

import structlog
from tavily import TavilyClient
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import settings
from backend.models.research import RawSource, SourceCredibility, SourceType

log = structlog.get_logger(__name__)

# Domains known to be high-credibility news / financial sources
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


class WebSearchTool:
    """
    Wraps the Tavily search API and converts results to RawSource objects.

    Example::

        tool = WebSearchTool()
        sources = await tool.search("AI impact on journalism 2024", max_results=8)
    """

    def __init__(self) -> None:
        self._client = TavilyClient(api_key=settings.tavily_api_key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_depth: str = "advanced",
        include_domains: Optional[list[str]] = None,
        exclude_domains: Optional[list[str]] = None,
        days: Optional[int] = None,
    ) -> list[RawSource]:
        """
        Execute a Tavily search and return a list of RawSource objects.

        Args:
            query: Natural-language search query.
            max_results: Maximum number of results to return (1–20).
            search_depth: "basic" (fast) or "advanced" (thorough, more tokens).
            include_domains: Restrict results to these domains.
            exclude_domains: Exclude results from these domains.
            days: Limit results to the last N days (None = no restriction).

        Returns:
            List of RawSource objects sorted by relevance score descending.
        """
        log.info("web_search.start", query=query, max_results=max_results)

        kwargs: dict[str, Any] = {
            "query": query,
            "max_results": min(max_results, 20),
            "search_depth": search_depth,
            "include_answer": True,
            "include_raw_content": False,
        }
        if include_domains:
            kwargs["include_domains"] = include_domains
        if exclude_domains:
            kwargs["exclude_domains"] = exclude_domains
        if days:
            kwargs["days"] = days

        # Tavily client is synchronous; run in thread executor to stay async-friendly
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, lambda: self._client.search(**kwargs)
        )

        sources: list[RawSource] = []
        for result in response.get("results", []):
            sources.append(
                RawSource(
                    source_type=SourceType.WEB_SEARCH,
                    url=result.get("url"),
                    title=result.get("title", "Untitled"),
                    content=result.get("content", ""),
                    relevance_score=result.get("score", 0.5),
                    credibility=_infer_credibility(result.get("url")),
                    metadata={
                        "published_date": result.get("published_date"),
                        "tavily_answer": response.get("answer"),
                    },
                )
            )

        log.info("web_search.complete", query=query, results_count=len(sources))
        return sources

    async def multi_search(
        self,
        queries: list[str],
        max_results_per_query: int = 5,
    ) -> list[RawSource]:
        """Run multiple queries concurrently and deduplicate by URL."""
        tasks = [self.search(q, max_results=max_results_per_query) for q in queries]
        results_nested = await asyncio.gather(*tasks, return_exceptions=True)

        seen_urls: set[str] = set()
        all_sources: list[RawSource] = []
        for batch in results_nested:
            if isinstance(batch, Exception):
                log.warning("web_search.query_failed", error=str(batch))
                continue
            for src in batch:
                if src.url and src.url not in seen_urls:
                    seen_urls.add(src.url)
                    all_sources.append(src)

        return all_sources
