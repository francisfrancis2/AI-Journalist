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
from backend.services.prompt_loader import load_prompt
from backend.tools.financial_data import FinancialDataTool
from backend.tools.news_api import NewsAPITool
from backend.tools.rss_parser import RSSParserTool
from backend.tools.web_scraper import WebScraperTool
from backend.tools.web_search import WebSearchTool

log = structlog.get_logger(__name__)

_ALLOWED_SOURCES = {"tavily", "newsapi", "rss", "financial"}


# ── Structured output schema ──────────────────────────────────────────────────

class ResearchPlan(BaseModel):
    """Planner output — query decomposition + source routing decision."""
    topic_type: Literal["background", "news", "financial", "mixed"]
    use_sources: list[str]
    primary_queries: list[str]
    deep_dive_queries: list[str]
    human_story_queries: list[str]   # Case studies, personal stories, expert interviews
    financial_symbols: list[str]
    rss_keyword: str


# ── Editable prompt loaded from backend/prompts ──────────────────────────────



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
            SystemMessage(content=load_prompt("researcher")),
            HumanMessage(content=f"Topic: {topic}"),
        ]
        return await self._structured_llm.ainvoke(messages)

    @staticmethod
    def _normalise_sources(plan: ResearchPlan) -> set[str]:
        topic_defaults = {
            "background": {"tavily", "rss"},
            "news": {"tavily", "newsapi", "rss"},
            "financial": {"tavily", "newsapi", "rss", "financial"},
            "mixed": {"tavily", "newsapi", "rss"},
        }
        selected = {source.lower().strip() for source in plan.use_sources}
        selected = selected.intersection(_ALLOWED_SOURCES)
        selected.update(topic_defaults.get(plan.topic_type, {"tavily", "newsapi", "rss"}))
        if "newsapi" in selected:
            selected.add("rss")
        if plan.financial_symbols:
            selected.add("financial")
        return selected

    async def run(self, state: dict) -> dict:
        """
        Execute the research phase.

        Args:
            state: Current JournalistState.

        Returns:
            Partial state update dict with ``research_package`` populated.
        """
        topic: str = state["topic"]
        improvement_plan = state.get("quality_improvement_plan")
        start = time.monotonic()

        log.info(
            "researcher.start",
            topic=topic,
            has_improvement_plan=improvement_plan is not None,
        )

        # Step 1: Plan queries and route sources
        plan = await self._plan_queries(topic)
        use_sources = self._normalise_sources(plan)
        plan.use_sources = sorted(use_sources)

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

        # Improvement-plan gap queries — run via NewsAPI + RSS (different corpus to Tavily)
        gap_queries: list[str] = []
        if improvement_plan and improvement_plan.research_gaps:
            gap_queries = improvement_plan.research_gaps[:4]
            log.info("researcher.gap_queries", count=len(gap_queries))
            for i, q in enumerate(gap_queries[:2]):
                fetch_tasks[f"news_gap_{i}"] = self._news.search_everything(
                    q, page_size=settings.news_api_page_size
                )
            # Gap RSS: use first gap as keyword to pull fresh editorial angles
            fetch_tasks["rss_gaps"] = self._rss.fetch_all_default_feeds(
                max_entries_per_feed=5, keyword_filter=gap_queries[0].split()[0]
            )

        if "tavily" in use_sources:
            base_queries = (plan.primary_queries + plan.deep_dive_queries)[:6]
            fetch_tasks["web"] = self._search.multi_search(
                base_queries,
                max_results_per_query=settings.tavily_max_results,
            )

        # Human-story queries always run via NewsAPI for person/case-study coverage
        for i, q in enumerate(plan.human_story_queries[:2]):
            fetch_tasks[f"news_human_{i}"] = self._news.search_everything(
                q, page_size=settings.news_api_page_size
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
