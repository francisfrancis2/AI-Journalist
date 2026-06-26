"""
Research Agent — first node in the journalist pipeline.

Responsibilities:
  1. Classify the topic and route to the relevant data sources.
  2. Decompose the topic into targeted sub-queries.
  3. Execute parallel searches via routed sources only.
  4. Scrape the most promising URLs for full article text.
    5. Package all raw sources into a ResearchPackage for AnglesAndHooksAgent.
"""

import asyncio
import time
from typing import Any, Literal

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import (
    RawSource,
    ResearchPackage,
    ResearchQuery,
    SourceCredibility,
    SourceType,
)
from backend.services.prompt_loader import load_prompt
from backend.services.duration_targets import duration_prompt_block, duration_target_for
from backend.services.library_knowledge import (
    format_reference_pack,
    get_reference_pack,
    merge_reference_pack,
)
from backend.services.research_report import ResearchReportSynthesizer
from backend.tools.anthropic_deep_research import (
    AnthropicDeepResearchTool,
    DeepResearchCitation,
    DeepResearchResult,
)
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
    union of all archetypes to the web search providers; AnglesAndHooksAgent then has
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


class ResearchGaps(BaseModel):
    """Gap-detection output used by writer-driven research enrichment."""
    sufficient: bool = Field(
        description="True when the existing research already covers what the work in progress needs."
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Specific, search-ready queries for missing evidence (empty when sufficient).",
    )


class ConsolidatedResearch(BaseModel):
    """A consolidated research report returned by ResearchAgent.run_report."""
    report_markdown: str
    citations: list[DeepResearchCitation] = Field(default_factory=list)
    package: ResearchPackage
    model: str
    web_search_requests: int = 0


# ── Editable prompt loaded from backend/prompts ──────────────────────────────



class ResearchAgent:
    """
    Multi-source research agent powered by Tavily, optional Anthropic Search,
    NewsAPI, RSS, and Alpha Vantage financial data.

    Example::

        agent = ResearchAgent()
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
        self._gap_llm = _llm.with_structured_output(ResearchGaps)
        self._search = WebSearchTool()
        self._anthropic_search = AnthropicSearchTool() if settings.enable_anthropic_search else None
        self._news = NewsAPITool()
        self._rss = RSSParserTool()
        self._financial = FinancialDataTool()
        # Anthropic deep research is always available; gated per-call by
        # settings.enable_deep_research so cost stays tunable.
        self._deep_research = AnthropicDeepResearchTool()
        self._synthesizer = ResearchReportSynthesizer()

    async def _plan_queries(
        self,
        topic: str,
        *,
        state: dict | None = None,
        reference_pack=None,
    ) -> ResearchPlan:
        """Classify the topic and generate targeted search queries."""
        pack = reference_pack or get_reference_pack(
            role="research_agent",
            topic=topic,
            state=state,
            max_cards=4,
            token_budget=1000,
        )
        reference_context = format_reference_pack(pack)
        duration_target = duration_target_for(state.get("target_duration_minutes") if state else None)
        user_prompt = (
            f"Topic: {topic}\n\n"
            f"{duration_prompt_block(duration_target, role='Research Agent')}"
            f"For this duration, plan roughly {duration_target.analysis_findings_min}-"
            f"{duration_target.analysis_findings_max} usable findings for downstream agents. "
            f"Favor query precision over volume for shorter episodes, and broader evidence "
            f"coverage for longer episodes."
        )
        if reference_context:
            user_prompt += f"\n\n{reference_context}"
        messages = [
            SystemMessage(content=load_prompt("research")),
            HumanMessage(content=user_prompt),
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

    @staticmethod
    def _select_balanced_queries(plan: ResearchPlan, cap: int) -> list[str]:
        """Pick a capped query set while preserving the six evidence lanes."""
        buckets = [
            plan.economics_queries,
            plan.operations_queries,
            plan.human_story_queries,
            plan.origin_queries,
            plan.counterintuitive_queries,
            plan.visual_queries,
        ]
        selected: list[str] = []
        seen: set[str] = set()

        max_depth = max((len(bucket) for bucket in buckets), default=0)
        for depth in range(max_depth):
            for bucket in buckets:
                if depth >= len(bucket):
                    continue
                query = bucket[depth].strip()
                key = query.lower()
                if not query or key in seen:
                    continue
                selected.append(query)
                seen.add(key)
                if len(selected) >= cap:
                    return selected

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
        duration_target = duration_target_for(state.get("target_duration_minutes"))
        start = time.monotonic()

        log.info("researcher.start", topic=topic)

        # Step 1: Plan queries (6 benchmark archetypes) and route sources
        reference_pack = get_reference_pack(
            role="research_agent",
            topic=topic,
            state=state,
            max_cards=4,
            token_budget=1000,
        )
        plan = await self._plan_queries(topic, state=state, reference_pack=reference_pack)
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

        # Step 2-6: dispatch every routed source (incl. always-on deep research)
        # in parallel, dedupe, and scrape. Shared with run_report()/enrich().
        base_queries = self._select_balanced_queries(plan, duration_target.web_query_cap)
        news_queries = (
            plan.economics_queries[:2]
            + plan.counterintuitive_queries[:2]
            + plan.origin_queries[:1]
        )
        await self._run_gather(
            topic=topic,
            package=package,
            base_queries=base_queries,
            human_story_queries=plan.human_story_queries,
            news_queries=news_queries,
            rss_keyword=plan.rss_keyword,
            financial_symbols=plan.financial_symbols,
            use_sources=use_sources,
            duration_target=duration_target,
            deep=True,
            deep_prompt=self._deep_prompt(topic, state),
            # Pipeline research uses a lighter deep-research cap than the
            # Research Tab (run_report) to control per-story cost/latency.
            deep_max_uses=settings.anthropic_deep_research_pipeline_max_uses,
        )

        package.research_duration_seconds = time.monotonic() - start

        log.info(
            "researcher.complete",
            topic=topic,
            total_sources=package.total_sources,
            deep_research=bool(package.deep_research_report),
            deep_research_searches=package.deep_research_web_search_requests,
            duration=f"{package.research_duration_seconds:.1f}s",
        )

        return {
            "research_package": package,
            "needs_more_research": False,
            "reference_packs": merge_reference_pack(state, reference_pack),
        }

    # ── Shared gather + deep research ─────────────────────────────────────────

    @staticmethod
    def _deep_prompt(topic: str, state: dict | None) -> str:
        """Focus the deep-research call with the selected angle/hook when present."""
        parts = [topic]
        if state:
            if state.get("selected_angle"):
                parts.append(f"Angle to pursue: {state['selected_angle']}")
            if state.get("story_hook"):
                parts.append(f"Story hook: {state['story_hook']}")
        return "\n".join(parts)

    def _absorb_deep_research(
        self,
        package: ResearchPackage,
        result: DeepResearchResult,
        seen_urls: set[str],
    ) -> None:
        """Fold an Anthropic deep-research report + citations into the package."""
        report = (result.report_markdown or "").strip()
        if report:
            package.deep_research_report = (
                f"{package.deep_research_report}\n\n---\n\n{report}".strip()
                if package.deep_research_report
                else report
            )
        package.deep_research_web_search_requests += result.web_search_requests
        for citation in result.citations:
            if not citation.url or citation.url in seen_urls:
                continue
            seen_urls.add(citation.url)
            package.add_source(
                RawSource(
                    source_type=SourceType.WEB_SEARCH,
                    url=citation.url,
                    title=citation.title or citation.url,
                    content=citation.cited_text or citation.title or "",
                    credibility=SourceCredibility.MEDIUM,
                    relevance_score=0.6,
                    metadata={"provider": "anthropic_deep_research"},
                )
            )

    async def _run_gather(
        self,
        *,
        topic: str,
        package: ResearchPackage,
        base_queries: list[str],
        human_story_queries: list[str],
        news_queries: list[str],
        rss_keyword: str,
        financial_symbols: list[str],
        use_sources: set[str],
        duration_target,
        deep: bool,
        deep_prompt: str,
        deep_max_uses: int | None = None,
    ) -> None:
        """Dispatch all routed providers in parallel into ``package`` and scrape."""
        fetch_tasks: dict[str, Any] = {}

        if "tavily" in use_sources and base_queries:
            fetch_tasks["web"] = self._search.multi_search(
                base_queries,
                max_results_per_query=settings.tavily_max_results,
            )
            if self._anthropic_search is not None:
                fetch_tasks["web_anthropic"] = self._anthropic_search.multi_search(
                    base_queries[: settings.anthropic_search_max_queries],
                )

        for i, q in enumerate(human_story_queries[: duration_target.human_story_query_cap]):
            fetch_tasks[f"news_human_{i}"] = self._news.search_everything(
                q, page_size=settings.news_api_page_size
            )

        if "rss" in use_sources:
            fetch_tasks["rss"] = self._rss.fetch_all_default_feeds(
                max_entries_per_feed=duration_target.rss_entries_per_feed,
                keyword_filter=rss_keyword,
            )

        if "newsapi" in use_sources:
            for i, q in enumerate(news_queries[: duration_target.news_query_cap]):
                fetch_tasks[f"news_{i}"] = self._news.search_everything(
                    q, page_size=settings.news_api_page_size
                )

        if "financial" in use_sources and financial_symbols:
            for symbol in financial_symbols[:3]:
                fetch_tasks[f"fin_overview_{symbol}"] = self._financial.get_company_overview(symbol)
                fetch_tasks[f"fin_prices_{symbol}"] = self._financial.get_daily_prices(symbol)

        # Anthropic deep research — always on (gated by config) and merged into
        # the same package so downstream agents see a unified evidence set.
        deep_key = None
        if deep and settings.enable_deep_research:
            deep_key = "deep_research"
            fetch_tasks[deep_key] = self._deep_research.run_standalone(
                prompt=deep_prompt or topic,
                max_uses=deep_max_uses,
            )

        if not fetch_tasks:
            return

        task_keys = list(fetch_tasks.keys())
        task_results = await asyncio.gather(*fetch_tasks.values(), return_exceptions=True)

        # Dedupe by URL across the whole block, including any URLs the package
        # already holds (enrichment passes append to a populated package).
        seen_urls: set[str] = {s.url for s in package.sources if s.url}
        for key, result in zip(task_keys, task_results):
            if isinstance(result, Exception):
                log.warning("researcher.fetch_failed", source=key, error=str(result))
                continue
            if key == deep_key:
                self._absorb_deep_research(package, result, seen_urls)
                continue
            sources = result if isinstance(result, list) else [result]
            for src in sources:
                package.add_source_deduped(src, seen_urls)

        # Scrape top web results for full article text — skip URLs already scraped.
        scraped_urls = {
            s.url for s in package.sources
            if s.url and s.source_type.value == SourceType.WEB_SCRAPE.value
        }
        top_urls = [
            src.url for src in package.top_sources(duration_target.scrape_url_cap * 2)
            if src.url
            and src.source_type.value == SourceType.WEB_SEARCH.value
            and src.url not in scraped_urls
        ][: duration_target.scrape_url_cap]
        if top_urls:
            async with WebScraperTool() as scraper:
                scraped = await scraper.scrape_many(top_urls, concurrency=3)
                for src in scraped:
                    package.add_source(src)

    # ── Standalone consolidated report (Research Tab) ─────────────────────────

    async def run_report(
        self,
        *,
        prompt: str,
        existing_report: str | None = None,
        existing_citations: list[DeepResearchCitation] | None = None,
        deep: bool = True,
    ) -> ConsolidatedResearch:
        """
        Run the full multi-source (and optionally deep-research) gather for a
        free-form prompt, then synthesize ONE consolidated Markdown report +
        merged citations.

        Used by the Research Tab. When ``existing_report`` is provided this is a
        follow-up turn (extend / remove / refine the prior report). Pass
        ``deep=False`` on follow-ups so deep research runs only on the first
        query of a session (cost control).
        """
        topic = prompt.strip()
        state = {"topic": topic}
        duration_target = duration_target_for(None)
        start = time.monotonic()

        plan = await self._plan_queries(topic, state=state)
        use_sources = self._normalise_sources(plan)
        plan.use_sources = sorted(use_sources)
        base_queries = self._select_balanced_queries(plan, duration_target.web_query_cap)
        news_queries = (
            plan.economics_queries[:2]
            + plan.counterintuitive_queries[:2]
            + plan.origin_queries[:1]
        )

        package = ResearchPackage(topic=topic)
        await self._run_gather(
            topic=topic,
            package=package,
            base_queries=base_queries,
            human_story_queries=plan.human_story_queries,
            news_queries=news_queries,
            rss_keyword=plan.rss_keyword,
            financial_symbols=plan.financial_symbols,
            use_sources=use_sources,
            duration_target=duration_target,
            deep=deep,
            deep_prompt=topic,
        )
        package.research_duration_seconds = time.monotonic() - start

        report, citations = await self._synthesizer.synthesize(
            prompt=prompt,
            package=package,
            existing_report=existing_report,
            existing_citations=existing_citations,
        )
        log.info(
            "researcher.report_complete",
            topic=topic,
            total_sources=package.total_sources,
            citations=len(citations),
            web_search_requests=package.deep_research_web_search_requests,
        )
        return ConsolidatedResearch(
            report_markdown=report,
            citations=citations,
            package=package,
            model=settings.claude_opus_model,
            web_search_requests=package.deep_research_web_search_requests,
        )

    # ── Writer-driven gap detection + enrichment ──────────────────────────────

    async def detect_gaps(
        self,
        state: dict,
        *,
        draft_context: str,
        package: ResearchPackage,
    ) -> list[str]:
        """
        Inspect work-in-progress against existing research and return targeted
        search queries for missing evidence. Empty list ⇒ research is sufficient.
        """
        if not settings.enable_writer_research_enrichment:
            return []
        existing = "\n".join(f"- {src.title}" for src in package.top_sources(20))
        user_prompt = (
            f"Topic: {state.get('topic') or package.topic}\n\n"
            f"=== WORK IN PROGRESS ===\n{(draft_context or '').strip()[:3500]}\n\n"
            f"=== RESEARCH ALREADY GATHERED ===\n{existing[:3000] or '(none)'}\n\n"
            "Identify evidence GAPS that would materially strengthen this work: missing "
            "numbers, named protagonists, dates, primary sources, or counter-evidence. "
            f"Return at most {settings.research_enrichment_max_queries} specific, "
            "search-ready queries. If the existing research already covers what is "
            "needed, return sufficient=true and an empty gaps list."
        )
        try:
            result: ResearchGaps = await self._gap_llm.ainvoke(
                [
                    SystemMessage(
                        content="You identify missing evidence for a documentary script."
                    ),
                    HumanMessage(content=user_prompt),
                ]
            )
        except Exception as exc:
            log.warning("researcher.detect_gaps_failed", error=str(exc))
            return []
        if result.sufficient:
            return []
        queries: list[str] = []
        seen: set[str] = set()
        for q in result.gaps:
            cleaned = (q or "").strip()
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                queries.append(cleaned)
        return queries[: settings.research_enrichment_max_queries]

    async def enrich(
        self,
        state: dict,
        *,
        focus_queries: list[str],
        package: ResearchPackage,
    ) -> ResearchPackage:
        """
        Run a lighter, targeted research pass on ``focus_queries`` and merge the
        new evidence into ``package`` in place. Increments ``research_iterations``.
        """
        focus = [q for q in (focus_queries or []) if q.strip()][
            : settings.research_enrichment_max_queries
        ]
        if not focus:
            return package
        topic = state.get("topic") or package.topic
        duration_target = duration_target_for(state.get("target_duration_minutes"))
        deep_prompt = (
            "Targeted follow-up research for a documentary in progress.\n"
            f"Parent topic: {topic}\n"
            "Focus on these specific evidence gaps:\n"
            + "\n".join(f"- {q}" for q in focus)
        )
        log.info("researcher.enrich.start", topic=topic, gaps=len(focus))
        await self._run_gather(
            topic=topic,
            package=package,
            base_queries=focus,
            human_story_queries=[],
            news_queries=focus,
            rss_keyword="",
            financial_symbols=[],
            use_sources={"tavily", "newsapi"},
            duration_target=duration_target,
            deep=True,
            deep_prompt=deep_prompt,
            deep_max_uses=settings.anthropic_deep_research_enrichment_max_uses,
        )
        package.research_iterations += 1
        log.info(
            "researcher.enrich.complete",
            topic=topic,
            total_sources=package.total_sources,
            iterations=package.research_iterations,
        )
        return package
