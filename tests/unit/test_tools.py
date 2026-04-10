"""
Unit tests for data-source tools.
External HTTP calls are intercepted with respx / pytest-mock.
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import respx

from backend.models.research import SourceCredibility, SourceType


# ── WebSearchTool ─────────────────────────────────────────────────────────────

class TestWebSearchTool:
    def test_infer_credibility_high(self):
        from backend.tools.web_search import _infer_credibility
        assert _infer_credibility("https://reuters.com/article/123") == SourceCredibility.HIGH

    def test_infer_credibility_medium(self):
        from backend.tools.web_search import _infer_credibility
        assert _infer_credibility("https://techcrunch.com/2024/ai") == SourceCredibility.MEDIUM

    def test_infer_credibility_low(self):
        from backend.tools.web_search import _infer_credibility
        assert _infer_credibility("https://randomsitexyz.net/article") == SourceCredibility.LOW

    def test_infer_credibility_none(self):
        from backend.tools.web_search import _infer_credibility
        assert _infer_credibility(None) == SourceCredibility.LOW

    @pytest.mark.asyncio
    async def test_multi_search_deduplicates(self, mocker):
        """multi_search should remove duplicate URLs across queries."""
        from backend.tools.web_search import WebSearchTool
        from backend.models.research import RawSource

        shared_src = RawSource(
            source_type=SourceType.WEB_SEARCH,
            url="https://reuters.com/shared",
            title="Shared Article",
            content="Content",
            relevance_score=0.8,
        )

        async def _mock_search(query, max_results=5):
            return [shared_src]

        tool = WebSearchTool.__new__(WebSearchTool)
        tool.search = _mock_search  # type: ignore[assignment]

        results = await tool.multi_search(["query1", "query2"])
        # URL should appear only once despite two queries returning it
        urls = [r.url for r in results]
        assert urls.count("https://reuters.com/shared") == 1


# ── NewsAPITool ───────────────────────────────────────────────────────────────

class TestNewsAPITool:
    def test_article_to_source_maps_fields(self):
        from backend.tools.news_api import NewsAPITool

        article = {
            "source": {"id": "reuters", "name": "Reuters"},
            "title": "Test Headline",
            "description": "A short description.",
            "content": "Full article content here.",
            "url": "https://reuters.com/test",
            "author": "Jane Doe",
            "publishedAt": "2024-03-15T10:00:00Z",
        }
        src = NewsAPITool._article_to_source(article)
        assert src.source_type == SourceType.NEWS_API
        assert src.title == "Test Headline"
        assert src.credibility == SourceCredibility.HIGH  # reuters is high
        assert src.author == "Jane Doe"
        assert src.url == "https://reuters.com/test"
        assert "A short description." in src.content

    def test_article_to_source_unknown_source(self):
        from backend.tools.news_api import NewsAPITool

        article = {
            "source": {"id": None, "name": "Unknown Blog"},
            "title": "Blog Post",
            "description": "Desc",
            "content": "Content",
            "url": "https://someblog.com/post",
        }
        src = NewsAPITool._article_to_source(article)
        assert src.credibility == SourceCredibility.MEDIUM

    def test_parse_published_at(self):
        from backend.tools.news_api import _parse_published_at

        dt = _parse_published_at("2024-03-15T10:00:00Z")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 3

    def test_parse_published_at_invalid(self):
        from backend.tools.news_api import _parse_published_at

        assert _parse_published_at("not-a-date") is None
        assert _parse_published_at(None) is None


# ── RSSParserTool ─────────────────────────────────────────────────────────────

class TestRSSParserTool:
    def test_get_entry_content_prefers_atom_content(self):
        from backend.tools.rss_parser import _get_entry_content
        import feedparser

        # Simulate an Atom entry with content array
        class MockEntry:
            content = [{"value": "Full atom content"}]
            summary = "Short summary"

        assert _get_entry_content(MockEntry()) == "Full atom content"

    def test_get_entry_content_falls_back_to_summary(self):
        from backend.tools.rss_parser import _get_entry_content

        class MockEntry:
            content = []
            summary = "Summary text"

        assert _get_entry_content(MockEntry()) == "Summary text"

    @pytest.mark.asyncio
    async def test_fetch_all_default_feeds_handles_errors_gracefully(self, mocker):
        """If a feed fetch throws, the others should still return results."""
        from backend.tools.rss_parser import RSSParserTool
        from backend.models.research import SourceCredibility

        call_count = 0

        async def _mock_fetch(url, cred, max_entries, keyword_filter):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Feed unreachable")
            return []

        tool = RSSParserTool(feeds={"http://feed1.rss": SourceCredibility.HIGH,
                                     "http://feed2.rss": SourceCredibility.MEDIUM})
        tool.fetch_feed = _mock_fetch  # type: ignore[assignment]

        # Should not raise even though one feed fails
        results = await tool.fetch_all_default_feeds()
        assert isinstance(results, list)


# ── FinancialDataTool ─────────────────────────────────────────────────────────

class TestFinancialDataTool:
    @pytest.mark.asyncio
    async def test_get_company_overview_success(self, mocker):
        from backend.tools.financial_data import FinancialDataTool

        mock_data = {
            "Name": "NVIDIA Corporation",
            "Symbol": "NVDA",
            "Description": "Makes GPUs.",
            "MarketCapitalization": "3000000000000",
            "PERatio": "60",
            "Sector": "Technology",
        }

        mocker.patch.object(
            FinancialDataTool,
            "_get",
            new=AsyncMock(return_value=mock_data),
        )

        tool = FinancialDataTool()
        src = await tool.get_company_overview("NVDA")
        assert src.source_type == SourceType.FINANCIAL_DATA
        assert "NVIDIA" in src.title
        assert src.credibility == SourceCredibility.HIGH

    @pytest.mark.asyncio
    async def test_get_company_overview_raises_on_error(self, mocker):
        from backend.tools.financial_data import FinancialDataTool

        mocker.patch.object(
            FinancialDataTool,
            "_get",
            new=AsyncMock(side_effect=ValueError("Alpha Vantage error: Invalid API call")),
        )

        tool = FinancialDataTool()
        with pytest.raises(ValueError, match="Alpha Vantage error"):
            await tool.get_company_overview("INVALID")
