## Research Report Synthesizer

**Source file:** `backend/services/research_report.py`

### Responsibilities

Research report synthesis.

Merges an Anthropic deep-research narrative with the structured multi-source
findings collected by the Research Agent (Tavily / NewsAPI / RSS / financial /
Anthropic web search) into a single consolidated Markdown report.

Used by:
- The Research Tab (ResearchAgent.run_report) — the report shown to the user.
- The Scriptwriter — the research dossier attached to the final script.

### Model Configuration

- `ChatAnthropic(model=settings.claude_model, max_tokens=settings.claude_max_tokens)`

### Main Methods

- `ResearchReportSynthesizer.def __init__(self)`
- `ResearchReportSynthesizer.async def synthesize(self, *, prompt: str, package: ResearchPackage, existing_report: str | None=None, existing_citations: list[DeepResearchCitation] | None=None, conversation_turns: list[dict] | None=None)`

### System Prompt

This agent does not use an LLM system prompt.

### Run Logic

This file contains longer corpus-build helper flows. Review the source file for full implementation details.
