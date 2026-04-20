"""
FocusedResearchAgent — story-aware follow-up research for the Research tab.

Unlike the initial ResearcherAgent, this agent receives an existing story plus
evaluation/script context and decides which sources to query itself. The UI only
asks for the user's research goal and exposes a single "Start research" action.
"""

import asyncio
import time
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.models.research import FocusedResearchPlan, FocusedResearchRun, RawSource
from backend.tools.financial_data import FinancialDataTool
from backend.tools.news_api import NewsAPITool
from backend.tools.rss_parser import RSSParserTool
from backend.tools.web_search import WebSearchTool

log = structlog.get_logger(__name__)

_ALLOWED_SOURCES = {"tavily", "newsapi", "rss", "financial"}

_SYSTEM_PROMPT = """ROLE BOUNDARY: You are a story-aware documentary research planning agent.
You only plan follow-up research for the story context provided. Do not answer unrelated questions.

Your job is to build an optimized research plan that improves the story from a data,
source-quality, and evaluation point of view.

You will receive:
1. The user's research goal
2. Current story context
3. Editorial evaluation weaknesses/suggestions when available
4. Script audit and benchmark gaps when available
5. Existing source counts and source previews when available

Choose the source strategy yourself. The user does not choose source types.

Available sources:
- tavily: open-web background research, explainers, primary sources, company pages, reports
- newsapi: recent coverage, controversies, announcements, current reporting
- rss: trade press, ongoing editorial coverage, and Google News RSS aggregation
- financial: public companies, tickers, daily price history, company overview

Return:
- objective: concise restatement of the research mission
- evaluation_focus: the evaluation/script weaknesses this pass is meant to improve
- source_strategy: only use values from tavily, newsapi, rss, financial
- source_strategy_reasoning: why this mix is appropriate
- primary_queries: 3-5 broad authoritative queries
- deep_dive_queries: 3-5 specific queries for facts, numbers, counterpoints, or expert context
- financial_symbols: public-company tickers only, else empty
- rss_keyword: one keyword for RSS filtering
- expected_improvements: concrete ways this research should improve the script or evaluation

Prioritize factual accuracy, source diversity, stronger data points, and unresolved gaps.
Be specific and practical."""


class FocusedResearchAgent:
    """Runs story-aware follow-up research without exposing source selection to the UI."""

    def __init__(self) -> None:
        _llm = ChatAnthropic(
            model=settings.claude_haiku_model,
            api_key=settings.anthropic_api_key,
            max_tokens=1800,
            temperature=0.2,
        )
        self._structured_llm = _llm.with_structured_output(FocusedResearchPlan)
        self._search = WebSearchTool()
        self._news = NewsAPITool()
        self._rss = RSSParserTool()
        self._financial = FinancialDataTool()

    async def _build_plan(
        self,
        *,
        topic: str,
        user_input: str,
        story_context: str,
    ) -> FocusedResearchPlan:
        return await self._structured_llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Topic: {topic}\n\n"
                f"User research goal:\n{user_input}\n\n"
                f"Story context:\n{story_context}"
            )),
        ])

    @staticmethod
    def _normalise_sources(plan: FocusedResearchPlan) -> set[str]:
        selected = {source.lower().strip() for source in plan.source_strategy}
        selected = selected.intersection(_ALLOWED_SOURCES)
        if not selected:
            selected = {"tavily", "newsapi", "rss"}
        if plan.financial_symbols:
            selected.add("financial")
        return selected

    @staticmethod
    def _dedupe_sources(sources: list[RawSource]) -> list[RawSource]:
        seen: set[str] = set()
        deduped: list[RawSource] = []
        for source in sources:
            key = (source.url or source.title).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(source)
        return deduped

    async def run(
        self,
        *,
        topic: str,
        user_input: str,
        story_context: str,
    ) -> FocusedResearchRun:
        """Plan and execute one focused follow-up research pass."""
        start = time.monotonic()
        plan = await self._build_plan(
            topic=topic,
            user_input=user_input,
            story_context=story_context,
        )
        use_sources = self._normalise_sources(plan)
        plan.source_strategy = sorted(use_sources)

        log.info(
            "focused_research.start",
            topic=topic,
            sources=sorted(use_sources),
            financial_symbols=plan.financial_symbols,
        )

        fetch_tasks: dict[str, Any] = {}
        queries = [*plan.primary_queries, *plan.deep_dive_queries]

        if "tavily" in use_sources and queries:
            fetch_tasks["web"] = self._search.multi_search(
                queries[:5],
                max_results_per_query=3,
            )

        if "newsapi" in use_sources:
            for i, query in enumerate(plan.primary_queries[:2]):
                fetch_tasks[f"news_{i}"] = self._news.search_everything(
                    query,
                    page_size=min(settings.news_api_page_size, 8),
                    from_days_ago=45,
                )

        if "rss" in use_sources:
            fetch_tasks["rss"] = self._rss.fetch_all_default_feeds(
                max_entries_per_feed=6,
                keyword_filter=plan.rss_keyword or None,
            )

        if "financial" in use_sources and plan.financial_symbols:
            for symbol in plan.financial_symbols[:3]:
                fetch_tasks[f"fin_overview_{symbol}"] = self._financial.get_company_overview(symbol)
                fetch_tasks[f"fin_prices_{symbol}"] = self._financial.get_daily_prices(symbol)

        sources: list[RawSource] = []
        task_keys = list(fetch_tasks.keys())
        task_results = await asyncio.gather(*fetch_tasks.values(), return_exceptions=True)

        for key, result in zip(task_keys, task_results):
            if isinstance(result, Exception):
                log.warning("focused_research.fetch_failed", source=key, error=str(result))
                continue
            batch = result if isinstance(result, list) else [result]
            sources.extend(source for source in batch if isinstance(source, RawSource))

        sources = self._dedupe_sources(sources)
        summary = (
            f"Completed focused research using {', '.join(sorted(use_sources))}. "
            f"Collected {len(sources)} unique sources in {time.monotonic() - start:.1f}s."
        )

        log.info(
            "focused_research.complete",
            topic=topic,
            total_sources=len(sources),
            duration=f"{time.monotonic() - start:.1f}s",
        )
        return FocusedResearchRun(plan=plan, summary=summary, sources=sources)
