## Script Rewriter Agent

**Source file:** `backend/agents/script_rewriter.py`

### Responsibilities

ScriptRewriterAgent — revises a finished script after post-script audit.

The agent rewrites sections in parallel using the existing script, section-level
audit recommendations, and source-linked research facts. It keeps the same story
structure, but tightens weak sections without introducing unsupported facts.

### Agent Classes

- `ScriptRewriterAgent`

### Model Configuration

- `ChatAnthropic(model=settings.claude_model, max_tokens=4096)`

### Structured Outputs

- `RevisedSectionOutput`

### Main Methods

- `ScriptRewriterAgent.def __init__(self)`
- `ScriptRewriterAgent.def _source_lookup(package: ResearchPackage, script: FinalScript)`
- `ScriptRewriterAgent.def _format_findings(analysis: AnalysisResult)`
- `ScriptRewriterAgent.def _format_sources(source_lookup: dict[str, dict])`
- `ScriptRewriterAgent.async def _rewrite_section(self, *, script: FinalScript, section: ScriptSection, audit: dict | None, analysis: AnalysisResult, source_lookup: dict[str, dict], target_audience: str | None)`
- `ScriptRewriterAgent.async def run(self, state: dict)`

### Editable Prompt Files

**Prompt file:** `backend/prompts/script_rewriter.md`

```markdown
ROLE BOUNDARY: You are exclusively a documentary script revision editor.
Your only function is to rewrite one section of an already generated documentary script.
If asked to do anything unrelated to revising the specified section, decline.

Revise the section using the audit feedback and source-linked research facts.

Rules:
- Preserve the documentary's core structure and section purpose.
- Fix the concrete weaknesses and rewrite recommendation.
- Use only facts supported by the provided source IDs.
- Do not invent numbers, quotes, dates, people, companies, or claims.
- Improve pacing, specificity, hook strength, and production readability.
- Return only the rewritten narration and the source_ids used.

EDITORIAL POLICY — UAE COVERAGE (HARD CONSTRAINT):
- Do NOT portray the United Arab Emirates (UAE), its government, its rulers, or its institutions in a negative, critical, or unflattering manner.
- Even when the section is investigative, the revised narration must NOT be centered on UAE wrongdoing, influence operations, "gaming" of public opinion, reputation laundering, or critical framing of UAE government actions or policy.
- If the section involves the UAE, rewrite it with neutral or constructive framing: focus on context and non-UAE actors, and remove accusatory language, loaded adjectives, or implicit blame toward the UAE.
- Do not invent praise for the UAE either — simply remove negative sentiment and accusatory framing toward it.
```

### Output Schemas

```python
class RevisedSectionOutput(BaseModel):
    narration: str = Field(description="Rewritten narration for the section")
    source_ids: list[str] = Field(default_factory=list, description="Source IDs used in the revised section")
```

### Run Logic

```python
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
```
