"""
Researcher Agent — first node in the journalist pipeline.

Responsibilities:
  1. Classify the topic and route to the relevant data sources.
  2. Decompose the topic into targeted sub-queries.
  3. Execute parallel searches via routed sources only.
  4. Scrape the most promising URLs for full article text.
  5. Package all raw sources into a ResearchPackage for the Analyst.
"""

import asyncio
import time
from typing import Any, Literal

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from backend.config import settings
from backend.models.research import ResearchPackage, ResearchQuery, SourceType
from backend.tools.financial_data import FinancialDataTool
from backend.tools.news_api import NewsAPITool
from backend.tools.rss_parser import RSSParserTool
from backend.tools.web_scraper import WebScraperTool
from backend.tools.web_search import WebSearchTool

log = structlog.get_logger(__name__)


# ── Structured output schema ──────────────────────────────────────────────────

class ResearchPlan(BaseModel):
    """Planner output — query decomposition + source routing decision."""
    topic_type: Literal["background", "news", "financial", "mixed"]
    use_sources: list[str]
    primary_queries: list[str]
    deep_dive_queries: list[str]
    financial_symbols: list[str]
    rss_keyword: str


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a senior investigative research assistant for a documentary production company.
Decompose the topic into targeted search queries AND decide which data sources are relevant.
Do not include sources that will produce noise for this topic.

Source guide:
- tavily: open-web background research, company/industry context, non-financial topics
- newsapi: recent media coverage, breaking news, events from the last 30 days
- rss: ongoing editorial coverage, trade press, topical newsletters
- financial: stock prices, earnings, macro indicators — ONLY for public companies, markets, or economic policy

Classify the topic into one bucket:
- "background"  → tavily + rss (historical/contextual, science, culture, biography)
- "news"        → tavily + newsapi (current events, politics, recent controversies)
- "financial"   → tavily + newsapi + financial (markets, companies, economic policy)
- "mixed"       → tavily + newsapi + rss (broad topics spanning news and background)

Generate:
- 3-5 primary_queries: broad, authoritative queries
- 3-5 deep_dive_queries: specific angle queries
- financial_symbols: stock tickers if relevant, else empty list
- rss_keyword: single most important keyword for RSS filtering

Be specific. Include date contexts when relevant."""


class ResearcherAgent:
    """
    Multi-source research agent powered by Claude + Tavily + NewsAPI + RSS.

    Example::

        agent = ResearcherAgent()
        state_updates = await agent.run(state)
    """

    def __init__(self) -> None:
        _llm = ChatAnthropic(
            model=settings.claude_haiku_model,
            api_key=settings.anthropic_api_key,
            max_tokens=1536,
            temperature=0.2,
        )
        self._structured_llm = _llm.with_structured_output(ResearchPlan)
        self._search = WebSearchTool()
        self._news = NewsAPITool()
        self._rss = RSSParserTool()
        self._financial = FinancialDataTool()

    async def _plan_queries(self, topic: str) -> ResearchPlan:
        """Classify the topic and generate targeted search queries."""
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=f"Topic: {topic}"),
        ]
        return await self._structured_llm.ainvoke(messages)

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

        # Step 1: Plan queries and route sources
        plan = await self._plan_queries(topic)
        use_sources: set[str] = set(plan.use_sources)

        log.info(
            "researcher.routing",
            topic_type=plan.topic_type,
            use_sources=sorted(use_sources),
            financial_symbols=plan.financial_symbols,
        )

        package = ResearchPackage(topic=topic)
        package.queries_issued = [
            ResearchQuery(query_text=q, target_source_types=[SourceType.WEB_SEARCH])
            for q in plan.primary_queries + plan.deep_dive_queries
        ]

        # Steps 2-5: Fetch only routed sources in parallel
        fetch_tasks: dict[str, Any] = {}

        if "tavily" in use_sources:
            fetch_tasks["web"] = self._search.multi_search(
                (plan.primary_queries + plan.deep_dive_queries)[:5],
                max_results_per_query=settings.tavily_max_results,
            )

        if "rss" in use_sources:
            fetch_tasks["rss"] = self._rss.fetch_all_default_feeds(
                max_entries_per_feed=8, keyword_filter=plan.rss_keyword
            )

        if "newsapi" in use_sources:
            for i, q in enumerate(plan.primary_queries[:2]):
                fetch_tasks[f"news_{i}"] = self._news.search_everything(
                    q, page_size=settings.news_api_page_size
                )

        if "financial" in use_sources and plan.financial_symbols:
            for symbol in plan.financial_symbols[:3]:
                fetch_tasks[f"fin_overview_{symbol}"] = self._financial.get_company_overview(symbol)
                fetch_tasks[f"fin_prices_{symbol}"] = self._financial.get_daily_prices(symbol)

        task_keys = list(fetch_tasks.keys())
        task_results = await asyncio.gather(*fetch_tasks.values(), return_exceptions=True)

        for key, result in zip(task_keys, task_results):
            if isinstance(result, Exception):
                log.warning("researcher.fetch_failed", source=key, error=str(result))
                continue
            sources = result if isinstance(result, list) else [result]
            for src in sources:
                package.add_source(src)

        # Step 6: Scrape top web results for full article text
        top_urls = [
            src.url for src in package.top_sources(3)
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
