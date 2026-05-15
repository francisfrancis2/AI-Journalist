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
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import ResearchPackage, ResearchQuery, SourceType
from backend.services.prompt_loader import load_prompt
from backend.tools.financial_data import FinancialDataTool
from backend.tools.news_api import NewsAPITool
from backend.tools.rss_parser import RSSParserTool
from backend.tools.web_scraper import WebScraperTool
from backend.tools.anthropic_search import AnthropicSearchTool
from backend.tools.web_search import WebSearchTool

log = structlog.get_logger(__name__)

_ALLOWED_SOURCES = {"tavily", "newsapi", "rss", "financial"}


# ── Structured output schema ──────────────────────────────────────────────────

class ResearchPlan(BaseModel):
    """
    Planner output — six benchmark-style query archetypes plus source routing.

    Each archetype corresponds to a structural element that BI / Vox / CNBC Make It /
    Johnny Harris documentaries reliably contain. The researcher dispatches the
    union of all archetypes to the web search providers; the analyst then has
    everything it needs to pull numeric anchors, process steps, protagonists,
    origin events, counterintuitive claims, and visual artifacts.
    """
    topic_type: Literal["background", "news", "financial", "mixed"]
    use_sources: list[str]

    # ── Benchmark-style archetypes (each ≤ 3 queries) ──────────────────────────
    economics_queries: list[str] = Field(
        default_factory=list,
        description="Costs, margins, market sizes, dollar amounts (BI 'So Expensive', CNBC)",
    )
    operations_queries: list[str] = Field(
        default_factory=list,
        description="How it is made / who does the work / supply chain (BI 'Big Business')",
    )
    human_story_queries: list[str] = Field(
        default_factory=list,
        description="Named protagonists — workers, consumers, decision-makers (CNBC Make It)",
    )
    origin_queries: list[str] = Field(
        default_factory=list,
        description="How the status quo came to be, inflection points, decisions (Vox, JH)",
    )
    counterintuitive_queries: list[str] = Field(
        default_factory=list,
        description="Surprising / hidden / contrarian facts that produce the hook",
    )
    visual_queries: list[str] = Field(
        default_factory=list,
        description="Filmable locations, equipment, processes, archive candidates",
    )

    financial_symbols: list[str] = Field(default_factory=list)
    rss_keyword: str = ""


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
        self._anthropic_search = AnthropicSearchTool() if settings.enable_anthropic_search else None
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
        start = time.monotonic()

        log.info("researcher.start", topic=topic)

        # Step 1: Plan queries (6 benchmark archetypes) and route sources
        plan = await self._plan_queries(topic)
        use_sources = self._normalise_sources(plan)
        plan.use_sources = sorted(use_sources)

        # Build the union pool used by the broad web search providers.
        # Dedupe while preserving order so each archetype gets representation.
        seen_q: set[str] = set()
        all_archetype_queries: list[str] = []
        for q in (
            plan.economics_queries
            + plan.operations_queries
            + plan.human_story_queries
            + plan.origin_queries
            + plan.counterintuitive_queries
            + plan.visual_queries
        ):
            key = q.strip().lower()
            if not key or key in seen_q:
                continue
            seen_q.add(key)
            all_archetype_queries.append(q.strip())

        log.info(
            "researcher.routing",
            topic_type=plan.topic_type,
            use_sources=sorted(use_sources),
            financial_symbols=plan.financial_symbols,
            archetype_counts={
                "economics": len(plan.economics_queries),
                "operations": len(plan.operations_queries),
                "human_story": len(plan.human_story_queries),
                "origin": len(plan.origin_queries),
                "counterintuitive": len(plan.counterintuitive_queries),
                "visual": len(plan.visual_queries),
                "deduped_total": len(all_archetype_queries),
            },
        )

        package = ResearchPackage(topic=topic)
        package.queries_issued = [
            ResearchQuery(query_text=q, target_source_types=[SourceType.WEB_SEARCH])
            for q in all_archetype_queries
        ]

        # Step 2-5: dispatch sources in parallel
        fetch_tasks: dict[str, Any] = {}

        if "tavily" in use_sources:
            # Cap Tavily at 8 to bound cost while giving every archetype a chance.
            base_queries = all_archetype_queries[:8]
            fetch_tasks["web"] = self._search.multi_search(
                base_queries,
                max_results_per_query=settings.tavily_max_results,
            )
            # Anthropic's server-side web_search runs the same queries on a
            # different search engine (Brave) and can chain follow-up searches
            # within a single call. Different URL set → broader coverage.
            if self._anthropic_search is not None:
                fetch_tasks["web_anthropic"] = self._anthropic_search.multi_search(
                    base_queries[: settings.anthropic_search_max_queries],
                )

        # Human-story queries → NewsAPI for named-person / case-study coverage
        for i, q in enumerate(plan.human_story_queries[:2]):
            fetch_tasks[f"news_human_{i}"] = self._news.search_everything(
                q, page_size=settings.news_api_page_size
            )

        if "rss" in use_sources:
            fetch_tasks["rss"] = self._rss.fetch_all_default_feeds(
                max_entries_per_feed=8, keyword_filter=plan.rss_keyword
            )

        if "newsapi" in use_sources:
            # NewsAPI sees economics + counterintuitive queries because those
            # are the archetypes most likely to surface fresh news angles.
            extra_news = (plan.economics_queries[:1] + plan.counterintuitive_queries[:1])
            for i, q in enumerate(extra_news):
                fetch_tasks[f"news_{i}"] = self._news.search_everything(
                    q, page_size=settings.news_api_page_size
                )

        if "financial" in use_sources and plan.financial_symbols:
            for symbol in plan.financial_symbols[:3]:
                fetch_tasks[f"fin_overview_{symbol}"] = self._financial.get_company_overview(symbol)
                fetch_tasks[f"fin_prices_{symbol}"] = self._financial.get_daily_prices(symbol)

        task_keys = list(fetch_tasks.keys())
        task_results = await asyncio.gather(*fetch_tasks.values(), return_exceptions=True)

        # Dedupe by URL across the entire gather block (Tavily + Anthropic +
        # RSS + NewsAPI commonly point at the same article). Keeps the first
        # occurrence; later providers contribute only new URLs.
        seen_urls: set[str] = set()
        for key, result in zip(task_keys, task_results):
            if isinstance(result, Exception):
                log.warning("researcher.fetch_failed", source=key, error=str(result))
                continue
            sources = result if isinstance(result, list) else [result]
            for src in sources:
                url = getattr(src, "url", None)
                if url:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
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
