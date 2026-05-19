"""
Anthropic-powered deep research report generator.

This is used by the Research Workspace for additional research on an existing
story. It is read-only with respect to story/script records: it returns a report
and citations, but does not mutate pipeline artefacts.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from backend.config import settings

log = structlog.get_logger(__name__)


class DeepResearchCitation(BaseModel):
    title: str
    url: str
    cited_text: Optional[str] = None


class DeepResearchResult(BaseModel):
    report_markdown: str
    citations: list[DeepResearchCitation] = Field(default_factory=list)
    model: str
    web_search_requests: int = 0


def _attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_text_and_citations(content_blocks: list[Any]) -> tuple[str, list[DeepResearchCitation]]:
    text_parts: list[str] = []
    citations: list[DeepResearchCitation] = []
    seen_urls: set[str] = set()

    def add_citation(raw: Any) -> None:
        url = _attr(raw, "url")
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        citations.append(
            DeepResearchCitation(
                title=_attr(raw, "title") or url,
                url=url,
                cited_text=_attr(raw, "cited_text"),
            )
        )

    for block in content_blocks:
        block_type = _attr(block, "type")
        if block_type == "text":
            text_parts.append(_attr(block, "text", "") or "")
            for citation in _attr(block, "citations", []) or []:
                add_citation(citation)
        elif block_type == "web_search_tool_result":
            for result in _attr(block, "content", []) or []:
                add_citation(result)

    return "\n\n".join(part.strip() for part in text_parts if part.strip()), citations


def _usage_web_search_requests(response: Any) -> int:
    usage = _attr(response, "usage")
    server_tool_use = _attr(usage, "server_tool_use", {}) if usage else {}
    return int(_attr(server_tool_use, "web_search_requests", 0) or 0)


def _append_source_appendix(report: str, citations: list[DeepResearchCitation]) -> str:
    if not citations:
        return report.strip()
    if "## Sources" in report or "## Source" in report:
        return report.strip()

    source_lines = "\n".join(f"- [{citation.title}]({citation.url})" for citation in citations)
    return f"{report.strip()}\n\n## Sources Consulted\n{source_lines}"


class AnthropicDeepResearchTool:
    """Generate an Anthropic web-search-backed research report."""

    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_opus_model

    async def run(self, *, prompt: str, story_context: str) -> DeepResearchResult:
        instructions = f"""You are running deep research for a documentary research workspace.

Use Anthropic web search as the primary research source. Search broadly, then narrow toward
credible primary sources, official data, expert sources, reputable reporting, and recent
developments. Treat the existing script as read-only: do not rewrite the script and do not
suggest that the script has already changed.

Research request:
{prompt}

Story and existing script context:
{story_context}

Return a Markdown report with these sections:
# Additional Research Report
## Executive Brief
## New Findings
## Source Leads
## Verification Gaps
## Script-Relevance Notes
## Next Research Queries

Rules:
- Cite factual claims with source titles and URLs.
- Separate confirmed findings from leads that still need verification.
- Mention which existing act or claim the new information could strengthen.
- Do not provide rewritten script text.
- Do not recommend or trigger script regeneration."""

        # Claude Opus 4.7 is a reasoning model and rejects the `temperature`
        # argument at the API layer; omit it (matches analyst + script_evaluator).
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=settings.claude_max_tokens,
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": settings.anthropic_deep_research_max_uses,
                }
            ],
            messages=[{"role": "user", "content": instructions}],
        )

        report, citations = _extract_text_and_citations(response.content)
        if not report:
            raise RuntimeError("Anthropic deep research returned an empty report.")

        return DeepResearchResult(
            report_markdown=_append_source_appendix(report, citations),
            citations=citations,
            model=self._model,
            web_search_requests=_usage_web_search_requests(response),
        )
