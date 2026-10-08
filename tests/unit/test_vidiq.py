"""Unit tests for the vidIQ YouTube demand tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.agents.angles_and_hooks import compact_ideation_context
from backend.agents.research import ResearchAgent
from backend.config import settings
from backend.models.research import (
    ResearchPackage,
    SourceType,
    YouTubeDemandReport,
    YouTubeKeyword,
    YouTubeVideo,
)
from backend.tools.vidiq import (
    VidIQTool,
    _extract_embedded_json,
    _iso_to_seconds,
    _stems,
    _video_search_keywords,
    demand_report_to_sources,
)


def _kw(keyword: str, monthly: int) -> YouTubeKeyword:
    return YouTubeKeyword(keyword=keyword, estimated_monthly_search=monthly)


def _vid(title: str, seconds: int = 900) -> YouTubeVideo:
    return YouTubeVideo(video_id="x", title=title, duration_seconds=seconds)


class TestParsing:
    def test_iso_duration(self):
        assert _iso_to_seconds("PT16M45S") == 1005
        assert _iso_to_seconds("PT1H2M3S") == 3723
        assert _iso_to_seconds(None) == 0
        assert _iso_to_seconds("garbage") == 0

    def test_stems_unify_plurals(self):
        assert _stems("drone deliveries") == _stems("drones delivery")

    def test_stopwords_dropped(self):
        assert "the" not in _stems("the drone")

    def test_extract_embedded_json_from_hybrid_payload(self):
        payload = 'Research found 2 results.\n\nKeyword data (JSON):\n{"a": 1, "b": [2, 3]}'
        assert _extract_embedded_json(payload) == {"a": 1, "b": [2, 3]}

    def test_extract_embedded_json_passes_through_dicts(self):
        assert _extract_embedded_json({"results": []}) == {"results": []}

    def test_extract_embedded_json_returns_none_without_json(self):
        assert _extract_embedded_json("no json here") is None


class TestTopicFilter:
    """Relevance is derived from vidIQ keywords, so nothing is subject-specific."""

    vocabulary = {"drone", "cargo", "deliv", "heavy", "lift", "logis"}
    seed = {"cargo", "drone"}

    def _check(self, title: str, seconds: int = 900) -> bool:
        return VidIQTool._on_topic(_vid(title, seconds), self.vocabulary, self.seed)

    def test_keeps_on_topic_long_form(self):
        assert self._check("Drone Delivery Was Supposed to be the Future")

    def test_rejects_single_stem_match(self):
        # "drone" alone is not enough signal — this is how MURDER DRONES got in.
        assert not self._check("Vortex Cannon vs Drone")

    def test_rejects_entertainment_formats(self):
        assert not self._check("MURDER DRONES - Episode 1: Cargo Delivery")
        assert not self._check("Top 10 Best Cargo Drone Deliveries for 2026")

    def test_rejects_military(self):
        assert not self._check("Ukraine Cargo Drone Delivery Strike")

    def test_rejects_shorts_below_duration_floor(self):
        assert not self._check("Cargo Drone Delivery Explained", seconds=120)

    def test_requires_a_seed_stem(self):
        # Two vocabulary hits but neither from the seed.
        assert not self._check("Heavy Lift Logistics Explained")


class TestVideoSearchKeywordSelection:
    """Broad head terms must not drive the video search."""

    def test_prefers_specific_multiword_terms_over_raw_volume(self):
        keywords = [
            _kw("drone", 290_155),          # head term, single word
            _kw("drones", 110_700),         # head term, single word
            _kw("logistics", 66_734),       # no seed overlap
            _kw("drone delivery", 22_810),  # specific
            _kw("cargo drones", 4_008),     # specific, two seed stems
        ]
        picked = [k.keyword for k in _video_search_keywords(keywords, {"cargo", "drone"}, 2)]
        assert "drone" not in picked and "logistics" not in picked
        assert "cargo drones" in picked          # two seed stems ranks first

    def test_falls_back_when_nothing_specific_qualifies(self):
        keywords = [_kw("drone", 100), _kw("drones", 90)]
        picked = _video_search_keywords(keywords, {"cargo", "drone"}, 2)
        assert len(picked) == 2


class TestFailOpen:
    """vidIQ is enrichment: every failure must degrade, never raise."""

    @pytest.mark.asyncio
    async def test_disabled_tool_returns_none(self, monkeypatch):
        tool = VidIQTool()
        tool._api_key = None
        assert tool.enabled is False
        assert await tool.fetch_demand_report("anything") is None

    @pytest.mark.asyncio
    async def test_network_failure_returns_none(self, monkeypatch):
        from backend.config import settings

        monkeypatch.setattr(settings, "enable_vidiq", True)
        tool = VidIQTool()
        tool._api_key = "test-key"

        async def _boom(*args, **kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr("httpx.AsyncClient.post", _boom)
        assert await tool.fetch_demand_report("anything") is None


class TestSourceMapping:
    def test_videos_become_raw_sources(self):
        report = YouTubeDemandReport(
            topic="t", search_seed="s",
            videos=[YouTubeVideo(video_id="abc", title="T", view_count=5, duration_seconds=1005)],
        )
        sources = demand_report_to_sources(report)
        assert len(sources) == 1
        assert sources[0].source_type == SourceType.YOUTUBE_BENCHMARK
        assert sources[0].url == "https://youtube.com/watch?v=abc"

    def test_computed_fields_survive_serialization(self):
        """url/duration_display must reach the frontend, so they are computed fields."""
        video = YouTubeVideo(video_id="abc", title="T", duration_seconds=1005)
        dumped = video.model_dump(mode="json")
        assert dumped["url"] == "https://youtube.com/watch?v=abc"
        assert dumped["duration_display"] == "16:45"

    def test_package_defaults_to_no_demand(self):
        assert ResearchPackage(topic="t").youtube_demand is None


class TestVidIQLifecycle:
    @pytest.mark.asyncio
    async def test_research_report_vidiq_is_opt_in_and_forwarded(self):
        agent = ResearchAgent.__new__(ResearchAgent)
        package = ResearchPackage(topic="UAE business")
        agent.gather_initial_package = AsyncMock(return_value=package)
        agent._synthesizer = SimpleNamespace(
            model=settings.claude_haiku_model,
            synthesize=AsyncMock(return_value=("# Report", [])),
        )

        await agent.run_report(prompt="UAE business")
        assert agent.gather_initial_package.await_args.kwargs["include_vidiq"] is False

        agent.gather_initial_package.reset_mock()
        await agent.run_report(
            prompt="UAE business with seed evidence",
            include_vidiq=True,
            vidiq_topic="UAE business",
        )
        assert agent.gather_initial_package.await_args.kwargs["include_vidiq"] is True
        assert agent.gather_initial_package.await_args.kwargs["vidiq_topic"] == "UAE business"

    def test_later_ideation_context_reuses_saved_snapshot(self):
        story = SimpleNamespace(
            topic="UAE logistics",
            title="Logistics story",
            tone="explanatory",
            target_duration_minutes=10,
            ideation_stage="hook",
            selected_angle="The last-mile race",
            angles_data=[],
            story_hook=None,
            hook_options_data=[],
            chapters_data=[],
            attachment_data=[],
            youtube_demand_data={"seed_keyword": {"keyword": "UAE logistics"}},
        )

        context = compact_ideation_context(story)

        assert "Saved vidIQ demand snapshot (reuse only; do not fetch again)" in context
        assert "UAE logistics" in context
