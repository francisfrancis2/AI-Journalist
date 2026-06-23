"""
Unit tests for the research-session helpers and the deep-research tool's
re-synthesize flow.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.tools.anthropic_deep_research import (
    AnthropicDeepResearchTool,
    DeepResearchCitation,
    DeepResearchResult,
    _merge_citations,
)


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
    sent_instruction = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Latest EV battery trends" in sent_instruction
    assert "existing consolidated report" not in sent_instruction.lower()


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

    existing_report = "# Research Report\n\nFindings here."
    existing_citations = [DeepResearchCitation(title="Old", url="https://old.com")]

    result = await tool.resynthesize(
        existing_report=existing_report,
        existing_citations=existing_citations,
        prompt="Extend to cover Germany",
    )

    assert "Germany" in result.report_markdown
    sent_instruction = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Existing consolidated report" in sent_instruction
    assert existing_report in sent_instruction
    assert "Extend to cover Germany" in sent_instruction
    # Existing citation should be presented to the model so it can keep it relevant
    assert "https://old.com" in sent_instruction


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
