"""
Unit tests for the research-session helpers and the deep-research tool's
re-synthesize flow.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.config import settings
from backend.models.research import ResearchPackage
from backend.services.research_report import ResearchReportSynthesizer
from backend.tools.anthropic_deep_research import (
    AnthropicDeepResearchTool,
    DeepResearchCitation,
    DeepResearchResult,
    _merge_citations,
    _remove_recommended_next_steps,
)


def _sent_text(mock_client: AsyncMock) -> str:
    content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content)


def _make_text_block(text: str, citations: list[dict] | None = None) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.citations = []
    for citation in citations or []:
        sub = MagicMock()
        sub.url = citation["url"]
        sub.title = citation.get("title", citation["url"])
        sub.cited_text = citation.get("cited_text")
        block.citations.append(sub)
    return block


def _make_response(text: str, citations: list[dict], web_searches: int = 0) -> MagicMock:
    response = MagicMock()
    response.content = [_make_text_block(text, citations)]
    response.usage = MagicMock()
    response.usage.server_tool_use = {"web_search_requests": web_searches}
    return response


def test_merge_citations_dedupes_by_url_and_preserves_order():
    existing = [
        DeepResearchCitation(title="A", url="https://a.com"),
        DeepResearchCitation(title="B", url="https://b.com"),
    ]
    new = [
        DeepResearchCitation(title="B-restated", url="https://b.com"),  # dupe
        DeepResearchCitation(title="C", url="https://c.com"),
    ]
    merged = _merge_citations(existing, new)
    assert [c.url for c in merged] == [
        "https://a.com",
        "https://b.com",
        "https://c.com",
    ]
    assert merged[1].title == "B"  # existing entry wins on dupe


def test_merge_citations_drops_empty_urls():
    existing: list[DeepResearchCitation] = []
    new = [
        DeepResearchCitation(title="bad", url=""),
        DeepResearchCitation(title="good", url="https://good.com"),
    ]
    assert [c.url for c in _merge_citations(existing, new)] == ["https://good.com"]


def test_remove_recommended_next_steps_section():
    report = """# Research Report

## Key Findings

Useful finding.

## Recommended Next Steps

1. Internal follow-up action.
2. Another action.
"""

    cleaned = _remove_recommended_next_steps(report)

    assert "Useful finding." in cleaned
    assert "Recommended Next Steps" not in cleaned
    assert "Internal follow-up action" not in cleaned


def test_remove_recommended_next_steps_preserves_later_section():
    report = """## Recommended Next Steps

- Hidden action

## Appendix

Keep this.
"""

    assert _remove_recommended_next_steps(report) == "## Appendix\n\nKeep this."


@pytest.mark.asyncio
async def test_run_standalone_returns_report_and_citations(mocker):
    tool = AnthropicDeepResearchTool()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_response(
            "# Research Report\n\nFindings here.",
            citations=[{"title": "Source A", "url": "https://example.com/a"}],
            web_searches=3,
        )
    )
    mocker.patch.object(tool, "_client", mock_client)

    result = await tool.run_standalone(prompt="Latest EV battery trends")

    assert isinstance(result, DeepResearchResult)
    assert "Research Report" in result.report_markdown
    assert result.web_search_requests == 3
    assert [c.url for c in result.citations] == ["https://example.com/a"]
    # Standalone prompt should not reference 'existing report'
    request = mock_client.messages.create.call_args.kwargs
    sent_instruction = _sent_text(mock_client)
    assert "Latest EV battery trends" in sent_instruction
    assert "existing consolidated report" not in sent_instruction.lower()
    assert "## Recommended Next Steps" not in sent_instruction
    assert request["model"] == settings.claude_model
    assert request["tools"][0]["max_uses"] == 12
    assert request["messages"][0]["content"][-1]["cache_control"] == {
        "type": "ephemeral"
    }


@pytest.mark.asyncio
async def test_resynthesize_passes_existing_report_and_extends(mocker):
    tool = AnthropicDeepResearchTool()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_response(
            "# Research Report\n\nFindings here.\n\n## Germany update\n\nNew data.",
            citations=[{"title": "German source", "url": "https://example.de/news"}],
            web_searches=2,
        )
    )
    mocker.patch.object(tool, "_client", mock_client)

    existing_report = """# Research Report

Findings here.

## Recommended Next Steps

- This legacy section must not enter the prompt.
"""
    existing_citations = [DeepResearchCitation(title="Old", url="https://old.com")]

    result = await tool.resynthesize(
        existing_report=existing_report,
        existing_citations=existing_citations,
        prompt="Extend to cover Germany",
    )

    assert "Germany" in result.report_markdown
    sent_instruction = _sent_text(mock_client)
    assert "Existing consolidated report" in sent_instruction
    assert "Findings here." in sent_instruction
    assert "This legacy section must not enter the prompt" not in sent_instruction
    assert "## Recommended Next Steps" not in sent_instruction
    assert "Extend to cover Germany" in sent_instruction
    # Existing citation should be presented to the model so it can keep it relevant
    assert "https://old.com" in sent_instruction


@pytest.mark.asyncio
async def test_deep_research_honors_explicit_lower_search_budget(mocker):
    tool = AnthropicDeepResearchTool()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_response("# Research Report\n\nFindings.", citations=[])
    )
    mocker.patch.object(tool, "_client", mock_client)

    await tool.run_standalone(prompt="UAE business", max_uses=3)

    assert mock_client.messages.create.call_args.kwargs["tools"][0]["max_uses"] == 3


def test_deep_research_path_budgets_keep_hub_depth():
    assert settings.anthropic_deep_research_max_uses == 12
    assert settings.anthropic_deep_research_pipeline_max_uses == 3
    assert settings.anthropic_deep_research_idea_max_uses == 3
    assert settings.anthropic_deep_research_enrichment_max_uses == 3


def test_research_report_synthesizer_uses_sonnet(mocker):
    constructor = mocker.patch("backend.services.research_report.ChatAnthropic")

    ResearchReportSynthesizer()

    assert constructor.call_args.kwargs["model"] == settings.claude_model


@pytest.mark.asyncio
async def test_research_report_synthesis_caches_accumulated_context():
    synthesizer = ResearchReportSynthesizer.__new__(ResearchReportSynthesizer)
    synthesizer._llm = MagicMock()
    synthesizer._llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="# Research Report\n\nMerged findings.")
    )
    package = ResearchPackage(
        topic="UAE business",
        deep_research_report="# Research Report\n\nFresh evidence.",
    )

    await synthesizer.synthesize(
        prompt="Extend the logistics section",
        package=package,
        existing_report="# Research Report\n\nExisting evidence.",
        conversation_turns=[
            {
                "prompt": "Research UAE business",
                "report_markdown": "# Research Report\n\nExisting evidence.",
            }
        ],
    )

    messages = synthesizer._llm.ainvoke.call_args.args[0]
    assert "Existing evidence" in messages[2].content
    assert "Research request" in messages[1].content[0]["text"]
    assert messages[-1].content[0]["cache_control"] == {"type": "ephemeral"}
    assert "Extend the logistics section" in messages[-1].content[0]["text"]
    assert "Fresh evidence" in messages[-1].content[1]["text"]

    cached_followup_text = messages[-1].content[0]["text"]
    synthesizer._llm.ainvoke.reset_mock()
    await synthesizer.synthesize(
        prompt="Now add aviation",
        package=package,
        existing_report="# Research Report\n\nLogistics added.",
        conversation_turns=[
            {
                "prompt": "Research UAE business",
                "report_markdown": "# Research Report\n\nExisting evidence.",
            },
            {
                "prompt": "Extend the logistics section",
                "report_markdown": "# Research Report\n\nLogistics added.",
            },
        ],
    )

    next_messages = synthesizer._llm.ainvoke.call_args.args[0]
    assert next_messages[3].content[0]["text"] == cached_followup_text


@pytest.mark.asyncio
async def test_resynthesize_raises_on_empty_response(mocker):
    tool = AnthropicDeepResearchTool()
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_make_response("", citations=[]))
    mocker.patch.object(tool, "_client", mock_client)

    with pytest.raises(RuntimeError):
        await tool.resynthesize(
            existing_report="prior",
            existing_citations=[],
            prompt="follow up",
        )
