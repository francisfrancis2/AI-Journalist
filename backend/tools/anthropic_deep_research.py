"""
Anthropic-powered deep research report generator.

Used by the standalone Research Hub:
- `run_standalone(prompt)` — generate the first consolidated report from a free-form prompt.
- `resynthesize(existing_report, existing_citations, prompt)` — integrate a follow-up
  prompt (extension, removal, refinement) into the existing report and return an
  updated consolidated report + merged citation list.

Returns markdown + citations; never mutates any story/script record.
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


def _merge_citations(
    existing: list[DeepResearchCitation],
    new: list[DeepResearchCitation],
) -> list[DeepResearchCitation]:
    """Dedupe by URL, preserve order: existing first, then new."""
    merged: list[DeepResearchCitation] = []
    seen: set[str] = set()
    for citation in [*existing, *new]:
        url = citation.url
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(citation)
    return merged


def _format_existing_citations_for_prompt(
    citations: list[DeepResearchCitation],
    limit: int = 40,
) -> str:
    if not citations:
        return "(no prior citations)"
    lines: list[str] = []
    for index, citation in enumerate(citations[:limit], start=1):
        lines.append(f"{index}. {citation.title} — {citation.url}")
    if len(citations) > limit:
        lines.append(f"... and {len(citations) - limit} more")
    return "\n".join(lines)


class AnthropicDeepResearchTool:
    """Generate Anthropic web-search-backed research reports."""

    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_opus_model

    async def _call(self, instructions: str, *, max_uses: int | None = None) -> DeepResearchResult:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=settings.claude_max_tokens,
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": max_uses or settings.anthropic_deep_research_max_uses,
                }
            ],
            messages=[{"role": "user", "content": instructions}],
        )
        report, citations = _extract_text_and_citations(response.content)
        if not report:
            raise RuntimeError("Anthropic deep research returned an empty report.")
        return DeepResearchResult(
            report_markdown=report.strip(),
            citations=citations,
            model=self._model,
            web_search_requests=_usage_web_search_requests(response),
        )

    async def run_standalone(self, *, prompt: str, max_uses: int | None = None) -> DeepResearchResult:
        """Generate the first consolidated research report from a free-form prompt."""
        instructions = f"""You are running deep research for a documentary research hub.

Use Anthropic web search as the primary research source. Search broadly, then narrow toward
credible primary sources, official data, expert sources, reputable reporting, and recent
developments.

Research request:
{prompt}

Return a Markdown report with these sections (omit a section only when nothing applies):
# Research Report
## Executive Brief
## Key Findings
## Supporting Evidence
## Open Questions and Verification Gaps
## Recommended Next Steps

Rules:
- Cite factual claims with source titles and URLs inline.
- Separate confirmed findings from leads that still need verification.
- Be concrete: prefer numbers, dates, named sources over generalities.
- Do not invent sources or citations."""
        return await self._call(instructions, max_uses=max_uses)

    async def resynthesize(
        self,
        *,
        existing_report: str,
        existing_citations: list[DeepResearchCitation],
        prompt: str,
    ) -> DeepResearchResult:
        """
        Integrate a follow-up prompt into the existing report and return an
        updated consolidated report. Honors three intents:
          - Extend (add new findings, geographies, angles)
          - Remove (drop specific sections / information per user instruction)
          - Refine (rephrase, restructure, deepen specific parts)

        The returned report is the FULL updated consolidated document. Citations
        are merged downstream (existing + new, deduped by URL).
        """
        existing_citation_block = _format_existing_citations_for_prompt(existing_citations)
        instructions = f"""You are updating a consolidated research report in a documentary research hub.

The user has submitted a follow-up instruction. Determine the user's intent and update the report accordingly:
- EXTEND: research new findings (use web search) and integrate them into the relevant sections.
- REMOVE: delete the requested information from the report cleanly. Do not leave dangling references.
- REFINE: restructure, rephrase, or deepen the parts the user calls out.

If web search is needed, use it. If the user is only asking to remove or restructure existing content, do not invent new findings — just edit.

Existing consolidated report:
---
{existing_report}
---

Existing citations already known to the report (do not re-list these unless they remain relevant):
{existing_citation_block}

User follow-up instruction:
{prompt}

Output requirements:
- Return the FULL updated report in Markdown — not a diff, not just the new section. The output replaces the existing report verbatim.
- Preserve the existing section structure where it still applies. Add or remove sections as needed.
- Cite new factual claims with source titles and URLs inline.
- Do not invent sources or citations.
- Do not include preamble or commentary outside the report itself."""
        return await self._call(instructions)
