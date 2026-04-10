"""
Playwright-based web scraper that renders JavaScript-heavy pages and
extracts clean article content for the research pipeline.
"""

import asyncio
import re
from typing import Optional

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from tenacity import retry, stop_after_attempt, wait_fixed

from backend.config import settings
from backend.models.research import RawSource, SourceCredibility, SourceType

log = structlog.get_logger(__name__)

_BOILERPLATE_SELECTORS = [
    "nav", "header", "footer", "aside", ".advertisement", ".ad",
    ".cookie-banner", ".newsletter-signup", ".related-articles",
    "script", "style", "noscript",
]


def _clean_text(html: str) -> str:
    """Strip tags and collapse whitespace from HTML content."""
    soup = BeautifulSoup(html, "lxml")
    for selector in _BOILERPLATE_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    # Prefer article body if present
    article = soup.find("article") or soup.find(id="article-body") or soup.body
    text = article.get_text(separator="\n") if article else soup.get_text(separator="\n")

    # Collapse blank lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _extract_meta(soup: BeautifulSoup, name: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"name": name}) or soup.find(
        "meta", attrs={"property": f"og:{name}"}
    )
    return tag.get("content") if tag else None


class WebScraperTool:
    """
    Async Playwright scraper.  Uses a single shared browser instance across
    scrapes; call ``start()`` / ``stop()`` explicitly or use as async context
    manager.

    Example::

        async with WebScraperTool() as scraper:
            source = await scraper.scrape("https://example.com/article")
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Optional[Browser] = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=settings.playwright_headless,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        log.info("scraper.browser_started")

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        log.info("scraper.browser_stopped")

    async def __aenter__(self) -> "WebScraperTool":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.stop()

    def _require_browser(self) -> Browser:
        if not self._browser:
            raise RuntimeError("Call start() before scraping or use as async context manager.")
        return self._browser

    @retry(stop=stop_after_attempt(1), wait=wait_fixed(1), reraise=True)
    async def scrape(self, url: str, wait_for: str = "domcontentloaded") -> RawSource:
        """
        Scrape a single URL and return a RawSource.

        Args:
            url: Full URL to scrape.
            wait_for: Playwright wait_until strategy ("load" | "domcontentloaded" | "networkidle").

        Returns:
            RawSource with extracted article text.
        """
        browser = self._require_browser()
        context: BrowserContext = await browser.new_context(
            user_agent=settings.playwright_user_agent,
            locale="en-US",
            java_script_enabled=True,
        )
        page: Page = await context.new_page()

        try:
            log.info("scraper.navigate", url=url)
            await page.goto(url, timeout=settings.playwright_timeout_ms, wait_until=wait_for)

            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            title = _extract_meta(soup, "title") or (
                soup.title.string.strip() if soup.title else url
            )
            description = _extract_meta(soup, "description") or ""
            author = _extract_meta(soup, "author")
            published = _extract_meta(soup, "article:published_time")

            body = _clean_text(html)
            # Combine description + body for richer content
            content = f"{description}\n\n{body}".strip() if description else body

            return RawSource(
                source_type=SourceType.WEB_SCRAPE,
                url=url,
                title=title,
                content=content[:8000],  # cap at ~8k chars
                author=author,
                credibility=SourceCredibility.MEDIUM,
                relevance_score=0.7,
                metadata={"word_count": len(content.split())},
            )
        finally:
            await page.close()
            await context.close()

    async def scrape_many(
        self, urls: list[str], concurrency: int = 3
    ) -> list[RawSource]:
        """Scrape multiple URLs with bounded concurrency."""
        semaphore = asyncio.Semaphore(concurrency)

        async def _scrape_limited(url: str) -> Optional[RawSource]:
            async with semaphore:
                try:
                    return await self.scrape(url)
                except Exception as exc:
                    log.warning("scraper.failed", url=url, error=str(exc))
                    return None

        results = await asyncio.gather(*[_scrape_limited(u) for u in urls])
        return [r for r in results if r is not None]
