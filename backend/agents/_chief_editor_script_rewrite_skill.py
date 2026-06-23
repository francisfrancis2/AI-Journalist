"""
Chief Editor Script Rewrite Skill — revises a finished script after post-script audit.

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
from backend.services.duration_targets import (
    WORDS_PER_MINUTE,
    duration_prompt_block,
    duration_target_for,
)
from backend.services.library_knowledge import (
    format_reference_pack,
    get_reference_pack,
    merge_reference_pack,
)
from backend.services.prompt_loader import load_prompt

log = structlog.get_logger(__name__)

_WORDS_PER_MINUTE = WORDS_PER_MINUTE


class RevisedSectionOutput(BaseModel):
    narration: str = Field(description="Rewritten narration for the section")
    source_ids: list[str] = Field(default_factory=list, description="Source IDs used in the revised section")




class ScriptRewriteSkill:
    """Chief Editor audit-driven script revision pass."""

    def __init__(self) -> None:
        _llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
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
        library_reference: str = "",
        voice_section: str = "",
        global_recommendations: list[str] | None = None,
        duration_contract: str = "",
    ) -> ScriptSection:
        audit_summary = "No section-specific audit was provided."
        if audit:
            audit_summary = (
                f"Summary: {audit.get('summary', '')}\n"
                f"Strengths: {'; '.join(audit.get('strengths', [])) or 'None listed'}\n"
                f"Weaknesses: {'; '.join(audit.get('weaknesses', [])) or 'None listed'}\n"
                f"Rewrite recommendation: {audit.get('rewrite_recommendation', '')}"
            )
        global_directives = ""
        if global_recommendations:
            global_directives = (
                "=== CHIEF EDITOR AUDIT RECOMMENDATIONS TO APPLY IN THIS REWRITE ===\n"
                "These recommendations were passed from the Chief Editor audit skill. Treat them as "
                "mandatory rewrite direction across all sections unless they conflict with verified source facts.\n"
                + "\n".join(f"- {item}" for item in global_recommendations)
                + "\n\n"
            )

        prompt = (
            f"Script title: {script.title}\n"
            f"Logline: {script.logline}\n"
            f"Target audience: {target_audience or script.metadata.get('target_audience') or 'General documentary audience'}\n\n"
            f"{duration_contract}"
            f"=== SECTION TO REVISE ===\n"
            f"Section {section.section_number}: {section.title}\n"
            f"Estimated seconds: {section.estimated_seconds}\n"
            f"Target section word count: {round(section.estimated_seconds / 60 * _WORDS_PER_MINUTE)}\n"
            f"Existing source IDs: {', '.join(section.source_ids) or 'None'}\n"
            f"Current narration:\n{section.narration}\n\n"
            f"{global_directives}"
            f"=== AUDIT FEEDBACK ===\n{audit_summary}\n\n"
            f"{library_reference}"
            f"{voice_section}"
            f"=== VERIFIED FINDINGS ===\n{self._format_findings(analysis)}\n\n"
            f"=== SOURCE LOOKUP ===\n{self._format_sources(source_lookup)}\n\n"
            "Return source_ids containing only IDs from the source lookup."
        )

        output: RevisedSectionOutput = await self._structured_llm.ainvoke([
            SystemMessage(content=load_prompt("chief_editor_evaluator")),
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
            raise ValueError("chief editor script rewrite received no final_script")
        if audit_report is None:
            raise ValueError("chief editor script rewrite received no script_audit_report")
        if analysis is None or package is None:
            raise ValueError("chief editor script rewrite requires analysis_result and research_package")

        source_lookup = self._source_lookup(package, script)
        duration_target = duration_target_for(
            state.get("target_duration_minutes")
            or script.metadata.get("target_duration_minutes")
        )
        rewrite_recommendations: list[str] = state.get("script_rewrite_recommendations") or []
        audit_by_section = {
            audit.section_number: audit.model_dump()
            for audit in audit_report.section_audits
        }
        reference_pack = get_reference_pack(
            role="chief_editor_evaluator",
            topic=state["topic"],
            state=state,
            max_cards=5,
            token_budget=1500,
        )
        reference_context = format_reference_pack(reference_pack)
        library_reference = ""
        if reference_context:
            library_reference = (
                f"=== REVISION LIBRARY REFERENCE ===\n{reference_context}\n"
                "Use this to tighten shape, specificity, and transitions without adding unsupported facts.\n\n"
            )

        voice_section = ""
        if settings.enable_team_voice_profile:
            voice_section = (
                "=== TEAM VOICE PROFILE (wording polish only) ===\n"
                "You are rewriting a section of an existing script based on the audit "
                "report above.\n\n"
                "Your rewrite decisions follow a clear hierarchy:\n"
                "1. PRIMARY — The library corpus reference pack (above), the existing "
                "storyline, and the audit report are the source of truth for what this "
                "section is, what role it plays in the larger script, and what the "
                "audit says needs to be fixed. The corpus tells you which craft patterns "
                "belong in this kind of section at this point in the documentary; the "
                "storyline tells you what this section must accomplish; the audit tells "
                "you which specific weaknesses to address. Solve the audit issues using "
                "craft patterns the corpus supports.\n\n"
                "2. SECONDARY — Voice is the final polish on top of (1). Once your "
                "rewrite resolves the audit issues using corpus-supported craft, use the "
                "TEAM VOICE PROFILE below to ensure the rewritten prose still sounds "
                "like the team. Preserve voice devices already present in the section "
                "(pivots, contrast pairs, definitional reframes); where you add new "
                "prose, write it in the same voice the original scriptwriter used.\n\n"
                "Voice preservation rules:\n"
                "- Do not strip signature voice devices while fixing other issues. If "
                "you must remove one, replace it with another device from the profile.\n"
                "- When tightening for length, prefer cutting redundant sentences over "
                "cutting voice devices.\n"
                "- When fixing factual issues, change the factual claim only — keep the "
                "surrounding voice intact.\n"
                "- Anti-patterns apply to your rewrites the same as to original writes. "
                "Never introduce one while fixing something else.\n\n"
                "Conflict resolution:\n"
                "- If an audit recommendation can ONLY be addressed by violating a voice "
                "rule (rare), the audit fix wins. Note the trade-off in your output.\n"
                "- If solving the audit would require contradicting a corpus craft "
                "pattern, prefer the corpus pattern and revise the audit-fix approach.\n\n"
                + load_prompt("team_voice_profile")
                + "\n=== END TEAM VOICE PROFILE ===\n\n"
            )
        duration_contract = (
            f"{duration_prompt_block(duration_target, role='Chief Editor Script Rewrite')}"
            f"Target total word count: {duration_target.target_word_count}. "
            "Preserve or adjust each section so the rewritten script stays aligned "
            "with the requested runtime.\n\n"
        )

        log.info(
            "chief_editor.script_rewrite.start",
            title=script.title,
            sections=len(script.sections),
            rewrite_recommendations=len(rewrite_recommendations),
        )

        revised_sections = await asyncio.gather(*[
            self._rewrite_section(
                script=script,
                section=section,
                audit=audit_by_section.get(section.section_number),
                analysis=analysis,
                source_lookup=source_lookup,
                target_audience=state.get("target_audience"),
                library_reference=library_reference,
                voice_section=voice_section,
                global_recommendations=rewrite_recommendations,
                duration_contract=duration_contract,
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
                "library_reference_cards": len(reference_pack.cards),
            },
        )

        log.info(
            "chief_editor.script_rewrite.complete",
            title=revised.title,
            word_count=revised.total_word_count,
        )

        return {
            "final_script": revised,
            "script_revision_cycle": state.get("script_revision_cycle", 0) + 1,
            "reference_packs": merge_reference_pack(state, reference_pack),
        }
