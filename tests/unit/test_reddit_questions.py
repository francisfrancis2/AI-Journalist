"""Tests for the Reddit community-question source.

Reddit's own JSON answers 403 to datacenter traffic, so this searches through
Tavily with a domain filter. That means the results include subreddit landing
pages and user profiles alongside real threads, and the filtering is what makes
the output usable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.models.research import RawSource, SourceType
from backend.tools.reddit_questions import (
    RedditQuestionTool,
    _clean_title,
    _looks_like_a_question,
    _to_question,
)


def _result(url: str, title: str) -> RawSource:
    return RawSource(source_type=SourceType.WEB_SEARCH, url=url, title=title, content="")


class TestPostDetection:
    def test_keeps_a_real_thread(self):
        q = _to_question(_result(
            "https://www.reddit.com/r/SmallBusinessUAE/comments/1od9w24/ask_me_anything/",
            "Should I choose Mainland or a Free Zone?",
        ))
        assert q is not None
        assert q.subreddit == "SmallBusinessUAE"

    def test_rejects_a_user_profile(self):
        """Search returned these; they carry no question."""
        assert _to_question(_result("https://www.reddit.com/user/Juriszone", "u/Juriszone")) is None

    def test_rejects_a_subreddit_landing_page(self):
        assert _to_question(_result(
            "https://www.reddit.com/r/Paramount_Zone", "r/Paramount_Zone"
        )) is None

    def test_rejects_a_title_too_short_to_be_a_question(self):
        assert _to_question(_result(
            "https://www.reddit.com/r/dubai/comments/abc123/x/", "Help"
        )) is None


class TestQuestionShape:
    @pytest.mark.parametrize("title", [
        "Should I choose Mainland or a Free Zone?",
        "How common is it in Dubai to buy an employment visa",
        "Can I open a business in UAE if I'm living abroad",
        "Advice about starting a Company in Free zone UAE",
        "Anyone with experience of starting business in UAE?",
    ])
    def test_accepts_question_shaped_titles(self, title):
        assert _looks_like_a_question(title)

    @pytest.mark.parametrize("title", [
        "DP World reports record container volumes",
        "New metro line opens next month",
    ])
    def test_rejects_announcements(self, title):
        assert not _looks_like_a_question(title)


class TestTitleCleaning:
    def test_strips_reddit_subreddit_suffix(self):
        assert _clean_title("Freezone vs Mainland : r/dubai") == "Freezone vs Mainland"

    def test_leaves_a_clean_title_alone(self):
        assert _clean_title("Late Payments - What is the Solution?") == (
            "Late Payments - What is the Solution?"
        )


class TestFetch:
    @pytest.mark.asyncio
    async def test_prefers_uae_operator_subreddits(self, mocker):
        tool = RedditQuestionTool()
        tool._search = type("S", (), {"search": AsyncMock(return_value=[
            _result("https://www.reddit.com/r/NoStupidQuestions/comments/a/x/",
                    "Why do people work in the UAE and Saudi?"),
            _result("https://www.reddit.com/r/SmallBusinessUAE/comments/b/y/",
                    "Should I choose Mainland or a Free Zone?"),
        ])})()

        report = await tool.fetch_questions()
        assert report is not None
        # The operator subreddit ranks first even though it came back second.
        assert report.questions[0].subreddit == "SmallBusinessUAE"

    @pytest.mark.asyncio
    async def test_returns_none_when_nothing_usable_comes_back(self, mocker):
        """Research must continue untouched, same contract as vidIQ."""
        tool = RedditQuestionTool()
        tool._search = type("S", (), {"search": AsyncMock(return_value=[
            _result("https://www.reddit.com/user/somebody", "u/somebody"),
        ])})()
        assert await tool.fetch_questions() is None

    @pytest.mark.asyncio
    async def test_a_search_failure_fails_open(self):
        tool = RedditQuestionTool()
        tool._search = type("S", (), {"search": AsyncMock(side_effect=RuntimeError("tavily down"))})()
        report = await tool.fetch_questions()
        assert report is None, "a provider failure must not raise into research"

    @pytest.mark.asyncio
    async def test_disabled_tool_returns_none_without_searching(self, monkeypatch):
        from backend.config import settings

        monkeypatch.setattr(settings, "reddit_questions_enabled", False)
        tool = RedditQuestionTool()
        search = AsyncMock()
        tool._search = type("S", (), {"search": search})()
        assert await tool.fetch_questions() is None
        search.assert_not_awaited()
