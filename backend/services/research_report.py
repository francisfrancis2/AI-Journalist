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
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.config import settings
from backend.models.research import ResearchPackage
from backend.services.llm_cache import cached_text
from backend.tools.anthropic_deep_research import (
    DeepResearchCitation,
    _merge_citations,
    _remove_recommended_next_steps,
)

log = structlog.get_logger(__name__)

_MAX_DIGEST_CHARS = 9000
_MAX_DEEP_REPORT_CHARS = 16000

_REPORT_SECTIONS = """# Research Report
## Executive Brief
## Key Findings
## Supporting Evidence
## Open Questions and Verification Gaps"""


def _initial_task(prompt: str) -> str:
    return f"Research request:\n{prompt}"


def _followup_task(prompt: str) -> str:
    return f"""Determine the user's intent from their follow-up instruction and update the report:

- EXTEND: integrate the new findings below into the relevant sections.
- REMOVE: delete the requested information cleanly, leaving no dangling references.
- REFINE: restructure, rephrase, or deepen the parts the user calls out.

User follow-up instruction:
{prompt}
"""


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
    """Single-call Sonnet synthesis of a consolidated research report."""

    def __init__(self) -> None:
        # Consolidating retrieved evidence is summarisation rather than the
        # high-stakes editorial reasoning reserved for Opus.
        self._llm = ChatAnthropic(
            model=settings.claude_model,
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
        conversation_turns: list[dict] | None = None,
    ) -> tuple[str, list[DeepResearchCitation]]:
        """
        Build one consolidated Markdown report + merged citation list.

        - ``prompt``: the research request (Research Tab prompt or story topic).
        - ``package``: the ResearchPackage (deep_research_report + structured sources).
        - ``existing_report``/``existing_citations``: when present, this is a
          follow-up turn — honor extend/remove/refine against the prior report.
        """
        # Strip the retired section before either source is placed in an LLM
        # prompt. This prevents legacy reports from spending context or output
        # tokens regenerating content that users must never receive.
        deep_report = _remove_recommended_next_steps(
            (package.deep_research_report or "").strip()
        )[:_MAX_DEEP_REPORT_CHARS]
        existing_report = _remove_recommended_next_steps(existing_report or "")
        digest = _structured_source_digest(package)
        structured_citations = _structured_citations(package)

        # Merged citation list: prior (if any) + deep-research + structured-source URLs.
        merged_citations = _merge_citations(
            existing_citations or [],
            structured_citations,
        )

        # Nothing to synthesize from — degrade gracefully to whatever we have.
        if not deep_report and not digest:
            return existing_report, merged_citations

        task = _followup_task(prompt) if existing_report else _initial_task(prompt)

        system_text = f"""You are a meticulous documentary research editor writing a consolidated research report.

Always return a single Markdown report with these sections (omit a section only when nothing applies):
{_REPORT_SECTIONS}

Rules:
- Merge the two inputs; prefer primary sources, official data, and recent reporting.
- Refer to source titles or publication names in prose when useful, but do not include raw URLs or Markdown links in the report body. The app shows links separately in the citation list.
- Separate confirmed findings from leads that still need verification.
- Be concrete: prefer numbers, dates, and named sources over generalities.
- Do not repeat the user's prompt or follow-up instruction in the report.
- Do not include a recommended next steps section or user action checklist.
- Do not invent sources or citations. Do not include commentary outside the report."""

        evidence_context = f"""You have TWO new evidence inputs to merge into the consolidated report. Do not output them
separately — weave them together, deduplicating overlapping facts.

=== DEEP RESEARCH NARRATIVE (Anthropic web search) ===
{deep_report or '(no deep-research narrative was produced)'}

=== STRUCTURED MULTI-SOURCE EVIDENCE (Tavily / NewsAPI / RSS / financial) ===
{digest or '(no structured sources were collected)'}"""

        # Research sessions already persist each completed prompt/report pair.
        # Reconstruct that append-only conversation so the prior turn remains
        # an exact prefix. The cache breakpoint is placed after this turn's
        # instruction and before its new evidence; the following turn can read
        # the accumulated history at cache rates while paying normally only for
        # the latest report and fresh evidence.
        messages: list = [SystemMessage(content=system_text)]
        completed_turns = [
            turn
            for turn in (conversation_turns or [])
            if isinstance(turn, dict)
            and str(turn.get("prompt") or "").strip()
            and str(turn.get("report_markdown") or "").strip()
        ]
        for index, turn in enumerate(completed_turns):
            historical_task = (
                _initial_task(str(turn["prompt"]))
                if index == 0
                else _followup_task(str(turn["prompt"]))
            )
            # Preserve the exact text-block shape that was cached when this
            # turn was current. Its evidence suffix is intentionally omitted:
            # the resulting consolidated assistant report supersedes it.
            messages.append(
                HumanMessage(
                    content=[{"type": "text", "text": historical_task}]
                )
            )
            messages.append(
                AIMessage(
                    content=_remove_recommended_next_steps(
                        str(turn["report_markdown"])
                    )
                )
            )
        if existing_report and not completed_turns:
            messages.append(
                HumanMessage(
                    content=(
                        "Use the current consolidated report below as the "
                        "document to update."
                    )
                )
            )
            messages.append(AIMessage(content=existing_report))
        messages.append(
            HumanMessage(
                content=[
                    *cached_text(task),
                    {"type": "text", "text": evidence_context},
                ]
            )
        )

        try:
            response = await self._llm.ainvoke(messages)
            report = (response.content if isinstance(response.content, str) else str(response.content)).strip()
        except Exception as exc:
            log.warning("research_report.synthesis_failed", error=str(exc))
            # Fall back to the deep-research narrative (or prior report) unmerged.
            report = deep_report or existing_report

        if not report:
            report = deep_report or existing_report
        return _remove_recommended_next_steps(report), merged_citations
