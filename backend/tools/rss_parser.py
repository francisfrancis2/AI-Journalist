"""
RSS / Atom feed parser.
Polls a curated list of feeds and converts entries to RawSource objects.
Uses feedparser (sync) wrapped in an executor for async compatibility.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser
import httpx
import structlog

from backend.config import settings
from backend.models.research import RawSource, SourceCredibility, SourceType

log = structlog.get_logger(__name__)

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
GOOGLE_NEWS_SEARCH_RSS_BASE = "https://news.google.com/rss/search"
RSS_FETCH_TIMEOUT_SECONDS = settings.rss_fetch_timeout_seconds

# Curated RSS feeds with pre-assigned credibility ratings
DEFAULT_FEEDS: dict[str, SourceCredibility] = {
    # High credibility
    "https://feeds.reuters.com/reuters/businessNews": SourceCredibility.HIGH,
    "https://feeds.bloomberg.com/markets/news.rss": SourceCredibility.HIGH,
    "https://www.ft.com/rss/home/uk": SourceCredibility.HIGH,
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml": SourceCredibility.HIGH,
    "https://feeds.nbcnews.com/nbcnews/public/business": SourceCredibility.HIGH,
    # Medium credibility
    "https://techcrunch.com/feed/": SourceCredibility.MEDIUM,
    "https://www.wired.com/feed/rss": SourceCredibility.MEDIUM,
    "https://feeds.feedburner.com/businessinsider": SourceCredibility.MEDIUM,
    "https://www.axios.com/feeds/feed.rss": SourceCredibility.MEDIUM,
    # Aggregator; article-level credibility varies by original publisher.
    GOOGLE_NEWS_RSS_URL: SourceCredibility.MEDIUM,
}


def _parse_date(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    """Try multiple feedparser date fields and return a timezone-aware datetime."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, field, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except Exception:
                pass

    # Fall back to the raw published string
    raw = getattr(entry, "published", None)
    if raw:
        try:
            return parsedate_to_datetime(raw)
        except Exception:
            pass

    return None


def _get_entry_content(entry: feedparser.FeedParserDict) -> str:
    """Extract the best available text content from a feed entry."""
    # Try full content first (Atom)
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    # Then summary / description
    return getattr(entry, "summary", "") or getattr(entry, "description", "")


def _build_google_news_search_feed(keyword_filter: Optional[str]) -> Optional[str]:
    """Return a topic-specific Google News RSS URL when a keyword is available."""
    if not keyword_filter:
        return None

    query = keyword_filter.strip()
    if not query:
        return None

    encoded_query = quote_plus(query)
    return f"{GOOGLE_NEWS_SEARCH_RSS_BASE}?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"


class RSSParserTool:
    """
    Polls RSS/Atom feeds and returns structured RawSource objects.

    Example::

        tool = RSSParserTool()
        sources = await tool.fetch_feed("https://feeds.reuters.com/reuters/businessNews")
        all_sources = await tool.fetch_all_default_feeds(max_entries_per_feed=5)
    """

    def __init__(self, feeds: Optional[dict[str, SourceCredibility]] = None) -> None:
        self._uses_default_feeds = feeds is None
        self._feeds = feeds if feeds is not None else DEFAULT_FEEDS

    async def _download_feed(self, url: str) -> bytes:
        timeout = httpx.Timeout(
            RSS_FETCH_TIMEOUT_SECONDS,
            connect=4.0,
            read=RSS_FETCH_TIMEOUT_SECONDS,
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "AI-Journalist RSS Reader/0.1"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

    async def fetch_feed(
        self,
        url: str,
        credibility: SourceCredibility = SourceCredibility.MEDIUM,
        max_entries: int = 20,
        keyword_filter: Optional[str] = None,
    ) -> list[RawSource]:
        """
        Fetch and parse a single RSS/Atom feed URL.

        Args:
            url: Feed URL.
            credibility: Pre-set credibility level for the feed.
            max_entries: Maximum number of entries to return.
            keyword_filter: If provided, only include entries whose title/summary
                            contains this keyword (case-insensitive).

        Returns:
            List of RawSource objects.
        """
        log.info("rss.fetch", url=url)

        try:
            content = await asyncio.wait_for(
                self._download_feed(url),
                timeout=RSS_FETCH_TIMEOUT_SECONDS + 2,
            )
            loop = asyncio.get_running_loop()
            parsed: feedparser.FeedParserDict = await loop.run_in_executor(
                None, lambda: feedparser.parse(content)
            )
        except asyncio.TimeoutError:
            log.warning("rss.fetch_timeout", url=url)
            return []
        except Exception as exc:
            log.warning("rss.fetch_failed", url=url, error=str(exc))
            return []

        if parsed.bozo and not parsed.entries:
            log.warning("rss.parse_error", url=url, exception=str(parsed.bozo_exception))
            return []

        sources: list[RawSource] = []
        kw = keyword_filter.lower() if keyword_filter else None

        for entry in parsed.entries[:max_entries]:
            title: str = getattr(entry, "title", "Untitled")
            content = _get_entry_content(entry)
            link = getattr(entry, "link", None)

            if kw and kw not in title.lower() and kw not in content.lower():
                continue

            sources.append(
                RawSource(
                    source_type=SourceType.RSS_FEED,
                    url=link,
                    title=title,
                    content=content[:4000],
                    published_at=_parse_date(entry),
                    credibility=credibility,
                    relevance_score=0.6,
                    metadata={
                        "feed_url": url,
                        "feed_title": parsed.feed.get("title", ""),
                        "author": getattr(entry, "author", None),
                        "tags": [t.term for t in getattr(entry, "tags", [])],
                    },
                )
            )

        log.info("rss.parsed", url=url, entries=len(sources))
        return sources

    async def fetch_all_default_feeds(
        self,
        max_entries_per_feed: int = 10,
        keyword_filter: Optional[str] = None,
        concurrency: int = 5,
    ) -> list[RawSource]:
        """
        Concurrently poll all feeds registered in this instance.

        Args:
            max_entries_per_feed: Cap on entries per feed.
            keyword_filter: Optional keyword to filter entries.
            concurrency: Number of feeds to poll in parallel.

        Returns:
            Deduplicated list of RawSource objects sorted by published_at descending.
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def _fetch(url: str, cred: SourceCredibility) -> list[RawSource]:
            async with semaphore:
                return await self.fetch_feed(
                    url, cred, max_entries_per_feed, keyword_filter
                )

        feeds = dict(self._feeds)
        google_news_search_feed = (
            _build_google_news_search_feed(keyword_filter)
            if self._uses_default_feeds
            else None
        )
        if google_news_search_feed and google_news_search_feed not in feeds:
            feeds[google_news_search_feed] = SourceCredibility.MEDIUM

        tasks = [_fetch(url, cred) for url, cred in feeds.items()]
        nested = await asyncio.gather(*tasks, return_exceptions=True)

        seen: set[str] = set()
        all_sources: list[RawSource] = []
        for batch in nested:
            if isinstance(batch, Exception):
                log.warning("rss.batch_error", error=str(batch))
                continue
            for src in batch:
                key = src.url or src.title
                if key not in seen:
                    seen.add(key)
                    all_sources.append(src)

        # Sort by recency (entries without dates go last)
        all_sources.sort(
            key=lambda s: s.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return all_sources

    async def add_feed(self, url: str, credibility: SourceCredibility) -> None:
        """Register a new feed URL for polling."""
        self._feeds[url] = credibility
        log.info("rss.feed_added", url=url, credibility=credibility)
