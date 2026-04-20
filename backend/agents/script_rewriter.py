"""
ScriptRewriterAgent — revises a finished script after post-script audit.

The agent rewrites sections in parallel using the existing script, section-level
audit recommendations, and source-linked research facts. It keeps the same story
structure, but tightens weak sections without introducing unsupported facts.
"""

import asyncio
import uuid

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import AnalysisResult, ResearchPackage
from backend.models.story import FinalScript, ScriptAuditReport, ScriptSection
from backend.services.script_storage import upload_script_to_s3

log = structlog.get_logger(__name__)

_WORDS_PER_MINUTE = 150


class RevisedSectionOutput(BaseModel):
    narration: str = Field(description="Rewritten narration for the section")
    source_ids: list[str] = Field(default_factory=list, description="Source IDs used in the revised section")


_SYSTEM_PROMPT = """ROLE BOUNDARY: You are exclusively a documentary script revision editor.
Your only function is to rewrite one section of an already generated documentary script.
If asked to do anything unrelated to revising the specified section, decline.

Revise the section using the audit feedback and source-linked research facts.

Rules:
- Preserve the documentary's core structure and section purpose.
- Fix the concrete weaknesses and rewrite recommendation.
- Use only facts supported by the provided source IDs.
- Do not invent numbers, quotes, dates, people, companies, or claims.
- Improve pacing, specificity, hook strength, and production readability.
- Return only the rewritten narration and the source_ids used."""


class ScriptRewriterAgent:
    """Audit-driven script revision pass."""

    def __init__(self) -> None:
        _llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=2048,
            temperature=0.3,
        )
        self._structured_llm = _llm.with_structured_output(RevisedSectionOutput)

    @staticmethod
    def _source_lookup(package: ResearchPackage, script: FinalScript) -> dict[str, dict]:
        lookup: dict[str, dict] = {}
        for src in package.top_sources(25):
            lookup[src.source_id] = {
                "title": src.title,
                "url": src.url,
                "credibility": src.credibility.value,
                "type": src.source_type.value,
                "excerpt": src.content[:700],
            }
        for src in script.sources:
            source_id = str(src.get("source_id") or "").strip()
            if not source_id or source_id in lookup:
                continue
            lookup[source_id] = {
                "title": src.get("title", "Untitled"),
                "url": src.get("url"),
                "credibility": src.get("credibility", "medium"),
                "type": src.get("type", "source"),
                "excerpt": "",
            }
        return lookup

    @staticmethod
    def _format_findings(analysis: AnalysisResult) -> str:
        return "\n".join(
            (
                f"- {finding.claim}"
                f" [source_ids: {', '.join(finding.supporting_source_ids) or 'unlinked'}]"
                f" [confidence: {finding.confidence:.2f}; category: {finding.category}]"
            )
            for finding in analysis.key_findings[:16]
        ) or "- No verified findings were extracted."

    @staticmethod
    def _format_sources(source_lookup: dict[str, dict]) -> str:
        return "\n".join(
            f"- {source_id}: {source.get('title', 'Untitled')} "
            f"({source.get('credibility', 'medium')}, {source.get('type', 'source')})\n"
            f"  Excerpt: {source.get('excerpt') or 'No excerpt available.'}"
            for source_id, source in list(source_lookup.items())[:20]
        ) or "- No source lookup available."

    async def _rewrite_section(
        self,
        *,
        script: FinalScript,
        section: ScriptSection,
        audit: dict | None,
        analysis: AnalysisResult,
        source_lookup: dict[str, dict],
        target_audience: str | None,
    ) -> ScriptSection:
        audit_summary = "No section-specific audit was provided."
        if audit:
            audit_summary = (
                f"Score: {audit.get('score', 0):.2f}\n"
                f"Summary: {audit.get('summary', '')}\n"
                f"Strengths: {'; '.join(audit.get('strengths', [])) or 'None listed'}\n"
                f"Weaknesses: {'; '.join(audit.get('weaknesses', [])) or 'None listed'}\n"
                f"Rewrite recommendation: {audit.get('rewrite_recommendation', '')}"
            )

        prompt = (
            f"Script title: {script.title}\n"
            f"Logline: {script.logline}\n"
            f"Target audience: {target_audience or script.metadata.get('target_audience') or 'General documentary audience'}\n\n"
            f"=== SECTION TO REVISE ===\n"
            f"Section {section.section_number}: {section.title}\n"
            f"Estimated seconds: {section.estimated_seconds}\n"
            f"Existing source IDs: {', '.join(section.source_ids) or 'None'}\n"
            f"Current narration:\n{section.narration}\n\n"
            f"=== AUDIT FEEDBACK ===\n{audit_summary}\n\n"
            f"=== VERIFIED FINDINGS ===\n{self._format_findings(analysis)}\n\n"
            f"=== SOURCE LOOKUP ===\n{self._format_sources(source_lookup)}\n\n"
            "Return source_ids containing only IDs from the source lookup."
        )

        output: RevisedSectionOutput = await self._structured_llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        valid_source_ids = [sid for sid in output.source_ids if sid in source_lookup]
        if not valid_source_ids:
            valid_source_ids = [sid for sid in section.source_ids if sid in source_lookup]

        return ScriptSection(
            section_number=section.section_number,
            title=section.title,
            narration=output.narration,
            estimated_seconds=section.estimated_seconds,
            source_ids=valid_source_ids,
        )

    async def run(self, state: dict) -> dict:
        script: FinalScript | None = state.get("final_script")
        audit_report: ScriptAuditReport | None = state.get("script_audit_report")
        analysis: AnalysisResult | None = state.get("analysis_result")
        package: ResearchPackage | None = state.get("research_package")
        if script is None:
            raise ValueError("script_rewriter received no final_script")
        if audit_report is None:
            raise ValueError("script_rewriter received no script_audit_report")
        if analysis is None or package is None:
            raise ValueError("script_rewriter requires analysis_result and research_package")

        source_lookup = self._source_lookup(package, script)
        audit_by_section = {
            audit.section_number: audit.model_dump()
            for audit in audit_report.section_audits
        }

        log.info(
            "script_rewriter.start",
            title=script.title,
            sections=len(script.sections),
            prior_score=f"{audit_report.overall_score:.2f}",
        )

        revised_sections = await asyncio.gather(*[
            self._rewrite_section(
                script=script,
                section=section,
                audit=audit_by_section.get(section.section_number),
                analysis=analysis,
                source_lookup=source_lookup,
                target_audience=state.get("target_audience"),
            )
            for section in script.sections
        ])

        total_words = sum(len(section.narration.split()) for section in revised_sections)
        revised = FinalScript(
            story_id=uuid.UUID(str(script.story_id)),
            title=script.title,
            logline=script.logline,
            opening_hook=script.opening_hook,
            sections=list(revised_sections),
            closing_statement=script.closing_statement,
            total_word_count=total_words,
            estimated_duration_minutes=round(total_words / _WORDS_PER_MINUTE, 1),
            sources=script.sources,
            metadata={
                **script.metadata,
                "revision_cycle": state.get("script_revision_cycle", 0) + 1,
                "revision_reason": "post_script_audit",
            },
        )

        s3_key: str | None = None
        try:
            s3_key = await upload_script_to_s3(
                revised,
                suffix=f"revision_{state.get('script_revision_cycle', 0) + 1}",
            )
        except Exception as exc:
            log.warning("script_rewriter.s3_upload_failed", error=str(exc))

        log.info(
            "script_rewriter.complete",
            title=revised.title,
            word_count=revised.total_word_count,
        )

        return {
            "final_script": revised,
            "script_s3_key": s3_key or state.get("script_s3_key"),
            "script_revision_cycle": state.get("script_revision_cycle", 0) + 1,
        }
