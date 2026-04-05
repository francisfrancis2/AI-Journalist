"""
Researcher Agent — first node in the journalist pipeline.

Responsibilities:
  1. Decompose the topic into targeted sub-queries.
  2. Execute parallel searches via Tavily, NewsAPI, and RSS feeds.
  3. Optionally scrape the most promising URLs with Playwright.
  4. Package all raw sources into a ResearchPackage for the Analyst.
"""

import time
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from backend.config import settings
from backend.models.research import ResearchPackage, ResearchQuery, SourceType
from backend.tools.financial_data import FinancialDataTool
from backend.tools.news_api import NewsAPITool
from backend.tools.rss_parser import RSSParserTool
from backend.tools.web_scraper import WebScraperTool
from backend.tools.web_search import WebSearchTool

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a senior investigative research assistant for a documentary production company.
Your goal is to generate a comprehensive set of search queries that will surface the most important facts,
data, human stories, and expert perspectives for a documentary on the given topic.

Return a JSON object with this exact structure:
{
  "primary_queries": ["<query1>", "<query2>", ...],  // 3-5 broad queries
  "deep_dive_queries": ["<query1>", ...],             // 3-5 specific angle queries
  "financial_symbols": ["TICKER1", "TICKER2"],       // stock tickers if relevant, else []
  "rss_keyword": "<single keyword for RSS filtering>" // most important keyword
}

Be specific. Target authoritative sources. Include date contexts when relevant."""


class ResearcherAgent:
    """
    Multi-source research agent powered by Claude + Tavily + NewsAPI + RSS.

    Example::

        agent = ResearcherAgent()
        state_updates = await agent.run(state)
    """

    def __init__(self) -> None:
        self._llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=2048,
            temperature=0.2,
        )
        self._search = WebSearchTool()
        self._news = NewsAPITool()
        self._rss = RSSParserTool()
        self._financial = FinancialDataTool()

    async def _plan_queries(self, topic: str) -> dict[str, Any]:
        """Ask Claude to decompose the topic into targeted search queries."""
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=f"Topic: {topic}"),
        ]
        response = await self._llm.ainvoke(messages)
        import json, re
        # Extract JSON block from the response
        text = response.content
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"LLM did not return valid JSON. Got: {text[:200]}")
        return json.loads(match.group())

    async def run(self, state: dict) -> dict:
        """
        Execute the research phase.

        Args:
            state: Current JournalistState.

        Returns:
            Partial state update dict with ``research_package`` populated.
        """
        topic: str = state["topic"]
        start = time.monotonic()

        log.info("researcher.start", topic=topic)

        # Step 1: Plan queries with Claude
        plan = await self._plan_queries(topic)
        primary_queries: list[str] = plan.get("primary_queries", [topic])
        deep_queries: list[str] = plan.get("deep_dive_queries", [])
        financial_symbols: list[str] = plan.get("financial_symbols", [])
        rss_keyword: str = plan.get("rss_keyword", topic.split()[0])

        package = ResearchPackage(topic=topic)
        package.queries_issued = [
            ResearchQuery(query_text=q, target_source_types=[SourceType.WEB_SEARCH])
            for q in primary_queries + deep_queries
        ]

        # Step 2: Web search (primary + deep dive)
        web_sources = await self._search.multi_search(
            primary_queries + deep_queries,
            max_results_per_query=settings.tavily_max_results,
        )
        for src in web_sources:
            package.add_source(src)

        # Step 3: NewsAPI
        for q in primary_queries[:2]:  # top 2 queries only to stay within rate limits
            news_sources = await self._news.search_everything(q, page_size=settings.news_api_page_size)
            for src in news_sources:
                package.add_source(src)

        # Step 4: RSS feeds filtered by keyword
        rss_sources = await self._rss.fetch_all_default_feeds(
            max_entries_per_feed=8, keyword_filter=rss_keyword
        )
        for src in rss_sources:
            package.add_source(src)

        # Step 5: Financial data if tickers were identified
        for symbol in financial_symbols[:3]:  # cap at 3 to manage API quota
            try:
                overview = await self._financial.get_company_overview(symbol)
                package.add_source(overview)
                prices = await self._financial.get_daily_prices(symbol)
                package.add_source(prices)
            except Exception as exc:
                log.warning("researcher.financial_data_failed", symbol=symbol, error=str(exc))

        # Step 6: Scrape the top 5 web sources for full article text
        top_urls = [
            src.url for src in package.top_sources(5)
            if src.url and src.source_type.value == SourceType.WEB_SEARCH.value
        ]
        if top_urls:
            async with WebScraperTool() as scraper:
                scraped = await scraper.scrape_many(top_urls, concurrency=3)
                for src in scraped:
                    package.add_source(src)

        package.research_duration_seconds = time.monotonic() - start

        log.info(
            "researcher.complete",
            topic=topic,
            total_sources=package.total_sources,
            duration=f"{package.research_duration_seconds:.1f}s",
        )

        return {
            "research_package": package,
            "needs_more_research": False,
        }
