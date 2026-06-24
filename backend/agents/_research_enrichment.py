"""
Shared writer-side research enrichment.

Chapter Writer and Scriptwriter use these helpers to pull *additional*,
gap-driven research from the unified ResearchAgent and fold it into the existing
ResearchPackage while writing. Kept separate so both call sites share one lazily
instantiated agent and one digest format.
"""

from __future__ import annotations

import structlog

from backend.config import settings
from backend.models.research import RawSource, ResearchPackage

log = structlog.get_logger(__name__)

# Lazily-instantiated shared Research Agent for writer enrichment. Lazy import
# avoids a circular import (research.py ← agents package ← this module).
_agent = None


def get_research_agent():
    global _agent
    if _agent is None:
        from backend.agents.research import ResearchAgent

        _agent = ResearchAgent()
    return _agent


async def enrich_if_gaps(
    state: dict,
    *,
    package: ResearchPackage | None,
    draft_context: str,
    label: str,
) -> list[RawSource]:
    """
    Detect evidence gaps in the work-in-progress and, if any, run ONE targeted
    enrichment pass that merges new sources into ``package`` in place.

    Returns the list of newly added sources (empty when research is sufficient,
    enrichment is disabled, or the iteration cap is reached).
    """
    if package is None or not settings.enable_writer_research_enrichment:
        return []
    if package.research_iterations >= settings.max_research_iterations:
        log.info("research_enrichment.cap_reached", label=label, iterations=package.research_iterations)
        return []

    agent = get_research_agent()
    before = {src.source_id for src in package.sources}
    try:
        gaps = await agent.detect_gaps(state, draft_context=draft_context, package=package)
    except Exception as exc:
        log.warning("research_enrichment.detect_failed", label=label, error=str(exc))
        return []
    if not gaps:
        log.info("research_enrichment.no_gaps", label=label)
        return []
    try:
        await agent.enrich(state, focus_queries=gaps, package=package)
    except Exception as exc:
        log.warning("research_enrichment.enrich_failed", label=label, error=str(exc))
        return []

    new_sources = [src for src in package.sources if src.source_id not in before]
    log.info(
        "research_enrichment.applied",
        label=label,
        gaps=len(gaps),
        new_sources=len(new_sources),
        iterations=package.research_iterations,
    )
    return new_sources


def fresh_research_digest(new_sources: list[RawSource], *, limit: int = 10) -> str:
    """Compact digest of newly gathered sources for a writer prompt."""
    lines: list[str] = []
    for index, src in enumerate(new_sources[:limit], start=1):
        credibility = getattr(src.credibility, "value", str(src.credibility))
        preview = (src.content or "").strip()[:320]
        lines.append(
            f"{index}. {src.title} [{credibility}]\n"
            f"   URL: {src.url or 'N/A'}\n"
            f"   {preview}"
        )
    return "\n".join(lines)
