"""What UAE operators are actually asking, from public Reddit threads.

Reddit's own JSON endpoints answer 403 to datacenter traffic, so this searches
Reddit through Tavily with ``include_domains`` rather than scraping it. That
also means no new credential: the Tavily key research already uses covers it.

The output is **demand evidence, not factual evidence**. A thread proves a
question is live and widely asked; it proves nothing about the answers in it.
Facts stay with the research sources, exactly as with the vidIQ signal.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

import structlog

from backend.config import settings
from backend.models.research import (
    CommunityQuestion,
    CommunityQuestionReport,
    RawSource,
)
from backend.tools.web_search import WebSearchTool

log = structlog.get_logger(__name__)

# Only a real post has /r/<sub>/comments/<id>/. Search also returns subreddit
# landing pages and user profiles, which carry no question at all.
_POST_URL_RE = re.compile(r"reddit\.com/r/(?P<sub>[A-Za-z0-9_]+)/comments/", re.I)

# Asked with no topic -- the Idea Generator case, where the point is to find out
# what operators want explained rather than to research a subject we already
# have. Deliberately phrased the way a founder would type it.
_FOUNDER_QUERIES = (
    "starting a business in UAE questions founders ask",
    "Dubai free zone vs mainland which should I choose",
    "UAE corporate tax small business what changed",
    "hiring staff in UAE visa cost reality",
    "getting paid late by clients UAE what to do",
)

# Subreddits where the question is likely to be from someone actually operating
# here. Used to rank, never to exclude: a good question in r/smallbusiness is
# still a good question.
_PREFERRED_SUBREDDITS = {
    "smallbusinessuae", "uae_startups", "startupsindubai", "dubai",
    "uae", "abudhabi", "dubaijobs", "smallbusiness", "entrepreneur",
}

_QUESTION_WORDS = (
    "how", "what", "why", "when", "where", "which", "who", "can i", "should i",
    "is it", "are there", "do i", "does anyone", "anyone know", "advice", "help",
)


def _looks_like_a_question(title: str) -> bool:
    """Keep titles that read as a question rather than an announcement."""
    lowered = (title or "").strip().lower()
    if not lowered:
        return False
    if lowered.endswith("?"):
        return True
    return any(lowered.startswith(word) or f" {word} " in lowered for word in _QUESTION_WORDS)


def _clean_title(title: str) -> str:
    """Strip Reddit's trailing ' : r/subreddit' from search result titles."""
    return re.sub(r"\s*:\s*r/[A-Za-z0-9_]+\s*$", "", title or "").strip()


def _to_question(source: RawSource) -> Optional[CommunityQuestion]:
    url = source.url or ""
    match = _POST_URL_RE.search(url)
    if not match:
        return None                     # a profile or subreddit page, not a post
    title = _clean_title(source.title)
    if len(title) < 12:
        return None
    return CommunityQuestion(question=title, url=url, subreddit=match.group("sub"))


class RedditQuestionTool:
    """Collects public questions about doing business in the UAE. Never raises."""

    def __init__(self) -> None:
        self._search = WebSearchTool()

    @property
    def enabled(self) -> bool:
        return bool(settings.reddit_questions_enabled and settings.tavily_api_key)

    async def fetch_questions(self, topic: Optional[str] = None) -> Optional[CommunityQuestionReport]:
        """Questions for a topic, or the standing founder set when there is none.

        Returns None on any failure so research continues untouched.
        """
        if not self.enabled:
            return None

        queries = (
            [f"{topic} UAE business reddit", f"{topic} Dubai advice reddit"]
            if topic
            else list(_FOUNDER_QUERIES)
        )
        queries = queries[: settings.reddit_questions_max_queries]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(
                        self._search.search(
                            query,
                            max_results=settings.reddit_questions_results_per_query,
                            include_domains=["reddit.com"],
                        )
                        for query in queries
                    ),
                    return_exceptions=True,
                ),
                timeout=settings.reddit_questions_timeout_seconds,
            )
        except asyncio.TimeoutError:
            log.warning("reddit_questions.timeout", topic=(topic or "")[:80])
            return None
        except Exception as exc:
            log.warning("reddit_questions.failed", error=str(exc)[:200])
            return None

        failures = sum(1 for row in results if isinstance(row, BaseException))
        questions: dict[str, CommunityQuestion] = {}
        rejected = 0
        for row in results:
            if isinstance(row, BaseException):
                continue
            for source in row:
                question = _to_question(source)
                if question is None:
                    rejected += 1
                    continue
                if not _looks_like_a_question(question.question):
                    rejected += 1
                    continue
                questions.setdefault(question.url, question)

        if not questions:
            log.info("reddit_questions.empty", topic=(topic or "")[:80], rejected=rejected)
            return None

        # Questions from UAE-operator subreddits first; everything else keeps its
        # search order behind them.
        ranked = sorted(
            questions.values(),
            key=lambda q: (q.subreddit or "").lower() not in _PREFERRED_SUBREDDITS,
        )[: settings.reddit_questions_max_questions]

        log.info(
            "reddit_questions.collected",
            topic=(topic or "founder-set")[:80],
            kept=len(ranked),
            rejected=rejected,
            queries=len(queries),
        )
        return CommunityQuestionReport(
            topic=topic or "UAE business operators",
            queries=queries,
            questions=ranked,
            partial=failures > 0,
        )


__all__ = ["RedditQuestionTool", "CommunityQuestionReport", "CommunityQuestion"]
