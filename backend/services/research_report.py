"""
Research report synthesis.

Merges an Anthropic deep-research narrative with the structured multi-source
findings collected by the Research Agent (Tavily / NewsAPI / RSS / financial /
Anthropic web search) into a single consolidated Markdown report.

Used by:
- The Research Tab (ResearchAgent.run_report) — the report shown to the user.
- The Scriptwriter — the research dossier attached to the final script.
"""

from __future__ import annotations

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.models.research import ResearchPackage
from backend.tools.anthropic_deep_research import (
    DeepResearchCitation,
    _merge_citations,
)

log = structlog.get_logger(__name__)

_MAX_DIGEST_CHARS = 9000
_MAX_DEEP_REPORT_CHARS = 16000

_REPORT_SECTIONS = """# Research Report
## Executive Brief
## Key Findings
## Supporting Evidence
## Open Questions and Verification Gaps
## Recommended Next Steps"""


def _structured_source_digest(package: ResearchPackage, limit: int = 16) -> str:
    """Compact digest of the strongest structured sources for the synthesis prompt."""
    lines: list[str] = []
    for index, src in enumerate(package.top_sources(limit), start=1):
        credibility = getattr(src.credibility, "value", str(src.credibility))
        source_type = getattr(src.source_type, "value", str(src.source_type))
        preview = (src.content or "").strip()[:600]
        lines.append(
            f"{index}. {src.title} [{credibility} | {source_type}]\n"
            f"   URL: {src.url or 'N/A'}\n"
            f"   {preview}"
        )
    return "\n".join(lines)[:_MAX_DIGEST_CHARS]


def _structured_citations(package: ResearchPackage, limit: int = 40) -> list[DeepResearchCitation]:
    """Derive citation objects from the structured sources that carry a URL."""
    citations: list[DeepResearchCitation] = []
    seen: set[str] = set()
    for src in package.top_sources(limit):
        url = src.url
        if not url or url in seen:
            continue
        seen.add(url)
        citations.append(DeepResearchCitation(title=src.title or url, url=url))
    return citations


class ResearchReportSynthesizer:
    """Single-call Opus synthesis of a consolidated research report."""

    def __init__(self) -> None:
        # Opus is a reasoning model and rejects `temperature`; omit it
        # (matches AngleSynthesisSkill / ScriptwriterAgent config).
        self._llm = ChatAnthropic(
            model=settings.claude_opus_model,
            api_key=settings.anthropic_api_key,
            max_tokens=settings.claude_max_tokens,
        )

    async def synthesize(
        self,
        *,
        prompt: str,
        package: ResearchPackage,
        existing_report: str | None = None,
        existing_citations: list[DeepResearchCitation] | None = None,
    ) -> tuple[str, list[DeepResearchCitation]]:
        """
        Build one consolidated Markdown report + merged citation list.

        - ``prompt``: the research request (Research Tab prompt or story topic).
        - ``package``: the ResearchPackage (deep_research_report + structured sources).
        - ``existing_report``/``existing_citations``: when present, this is a
          follow-up turn — honor extend/remove/refine against the prior report.
        """
        deep_report = (package.deep_research_report or "").strip()[:_MAX_DEEP_REPORT_CHARS]
        digest = _structured_source_digest(package)
        structured_citations = _structured_citations(package)

        # Merged citation list: prior (if any) + deep-research + structured-source URLs.
        merged_citations = _merge_citations(
            existing_citations or [],
            structured_citations,
        )

        # Nothing to synthesize from — degrade gracefully to whatever we have.
        if not deep_report and not digest:
            return (existing_report or "").strip(), merged_citations

        if existing_report:
            task = f"""You are updating a consolidated research report in a documentary research hub.

Determine the user's intent from their follow-up instruction and update the report:
- EXTEND: integrate the new findings below into the relevant sections.
- REMOVE: delete the requested information cleanly, leaving no dangling references.
- REFINE: restructure, rephrase, or deepen the parts the user calls out.

Existing consolidated report:
---
{existing_report.strip()}
---

User follow-up instruction:
{prompt}
"""
        else:
            task = f"""You are writing a consolidated research report for a documentary research hub.

Research request:
{prompt}
"""

        instructions = f"""{task}

You have TWO evidence inputs to merge into ONE report. Do not output them
separately — weave them together, deduplicating overlapping facts.

=== DEEP RESEARCH NARRATIVE (Anthropic web search) ===
{deep_report or '(no deep-research narrative was produced)'}

=== STRUCTURED MULTI-SOURCE EVIDENCE (Tavily / NewsAPI / RSS / financial) ===
{digest or '(no structured sources were collected)'}

Return a single Markdown report with these sections (omit a section only when nothing applies):
{_REPORT_SECTIONS}

Rules:
- Merge the two inputs; prefer primary sources, official data, and recent reporting.
- Refer to source titles or publication names in prose when useful, but do not include raw URLs or Markdown links in the report body. The app shows links separately in the citation list.
- Separate confirmed findings from leads that still need verification.
- Be concrete: prefer numbers, dates, and named sources over generalities.
- Do not repeat the user's prompt or follow-up instruction in the report.
- Do not invent sources or citations. Do not include commentary outside the report."""

        try:
            response = await self._llm.ainvoke(
                [
                    SystemMessage(content="You are a meticulous documentary research editor."),
                    HumanMessage(content=instructions),
                ]
            )
            report = (response.content if isinstance(response.content, str) else str(response.content)).strip()
        except Exception as exc:
            log.warning("research_report.synthesis_failed", error=str(exc))
            # Fall back to the deep-research narrative (or prior report) unmerged.
            report = deep_report or (existing_report or "").strip()

        if not report:
            report = deep_report or (existing_report or "").strip()
        return report, merged_citations
