"""
NewsAPI integration — fetches recent articles relevant to a topic and
converts them to RawSource objects for the research pipeline.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import settings
from backend.models.research import RawSource, SourceCredibility, SourceType

log = structlog.get_logger(__name__)

_BASE = settings.news_api_base_url

# NewsAPI source IDs with known high credibility
_CREDIBLE_SOURCE_IDS = {
    "reuters", "bloomberg", "the-wall-street-journal", "associated-press",
    "bbc-news", "cnbc", "financial-times", "the-economist",
}


def _map_credibility(source_id: Optional[str]) -> SourceCredibility:
    if source_id and source_id in _CREDIBLE_SOURCE_IDS:
        return SourceCredibility.HIGH
    return SourceCredibility.MEDIUM


def _parse_published_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class NewsAPITool:
    """
    Async wrapper around the NewsAPI v2 REST API.

    Example::

        tool = NewsAPITool()
        sources = await tool.search_everything("quantum computing breakthrough")
    """

    def __init__(self) -> None:
        self._headers = {"X-Api-Key": settings.news_api_key}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def search_everything(
        self,
        query: str,
        page_size: int = 20,
        from_days_ago: int = 30,
        language: str = "en",
        sort_by: str = "relevancy",  # relevancy | popularity | publishedAt
        domains: Optional[str] = None,
    ) -> list[RawSource]:
        """
        Search all articles across all sources and blogs.

        Args:
            query: Keywords or phrases to search for.
            page_size: Number of results (max 100 per NewsAPI docs).
            from_days_ago: Only return articles published in the last N days.
            language: Two-letter ISO language code.
            sort_by: Ranking strategy: relevancy, popularity, or publishedAt.
            domains: Comma-separated list of domain restrictions.

        Returns:
            List of RawSource objects.
        """
        from_date = (
            datetime.now(timezone.utc) - timedelta(days=from_days_ago)
        ).strftime("%Y-%m-%d")

        params: dict = {
            "q": query,
            "language": language,
            "from": from_date,
            "pageSize": min(page_size, 100),
            "sortBy": sort_by,
            "page": 1,
        }
        if domains:
            params["domains"] = domains

        log.info("news_api.search_everything", query=query)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{_BASE}/everything", params=params, headers=self._headers
            )
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "ok":
            log.error("news_api.error", message=data.get("message"))
            return []

        return [self._article_to_source(a) for a in data.get("articles", [])]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def top_headlines(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,  # business | technology | science | general
        country: str = "us",
        page_size: int = 10,
    ) -> list[RawSource]:
        """
        Fetch top headlines from major sources.

        Args:
            query: Optional keyword filter.
            category: NewsAPI category string.
            country: Two-letter country code.
            page_size: Number of articles (max 100).

        Returns:
            List of RawSource objects.
        """
        params: dict = {
            "country": country,
            "pageSize": min(page_size, 100),
        }
        if query:
            params["q"] = query
        if category:
            params["category"] = category

        log.info("news_api.top_headlines", query=query, category=category)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{_BASE}/top-headlines", params=params, headers=self._headers
            )
            response.raise_for_status()
            data = response.json()

        return [self._article_to_source(a) for a in data.get("articles", [])]

    @staticmethod
    def _article_to_source(article: dict) -> RawSource:
        source_info = article.get("source", {})
        source_id = source_info.get("id")
        source_name = source_info.get("name", "Unknown")

        content_parts = filter(
            None,
            [article.get("description"), article.get("content")],
        )
        content = "\n\n".join(content_parts) or article.get("title", "")

        return RawSource(
            source_type=SourceType.NEWS_API,
            url=article.get("url"),
            title=article.get("title", "Untitled"),
            content=content,
            author=article.get("author"),
            published_at=_parse_published_at(article.get("publishedAt")),
            credibility=_map_credibility(source_id),
            relevance_score=0.7,
            metadata={
                "source_id": source_id,
                "source_name": source_name,
                "url_to_image": article.get("urlToImage"),
            },
        )
