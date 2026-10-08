"""Cross-workspace contract for the canonical initial research operation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.agents.idea_generator import IdeaGeneratorAgent
from backend.agents.research import ResearchAgent
from backend.api.routes import stories
from backend.config import settings
from backend.models.idea_generation import IdeaFormat
from backend.models.research import ResearchPackage


@pytest.mark.asyncio
async def test_all_initial_workspaces_use_gather_initial_package(mocker) -> None:
    package = ResearchPackage(topic="UAE logistics")

    research_gather = AsyncMock(return_value=package)
    research_agent = ResearchAgent.__new__(ResearchAgent)
    research_agent.gather_initial_package = research_gather
    research_agent._synthesizer = SimpleNamespace(
        model=settings.claude_haiku_model,
        synthesize=AsyncMock(return_value=("# Research Report", [])),
    )
    await research_agent.run_report(
        prompt="UAE logistics",
        include_vidiq=True,
        vidiq_topic="UAE logistics",
    )

    idea_gather = AsyncMock(return_value=package)
    idea_agent = IdeaGeneratorAgent.__new__(IdeaGeneratorAgent)
    idea_agent._research = SimpleNamespace(gather_initial_package=idea_gather)
    mocker.patch(
        "backend.agents.idea_generator.VidIQTool.fetch_idea_trends",
        new=AsyncMock(return_value=None),
    )
    with pytest.raises(RuntimeError, match="insufficient_evidence"):
        await idea_agent.generate(IdeaFormat.DOCUMENTARY)

    story_gather = AsyncMock(return_value=package)
    mocker.patch.object(
        stories,
        "get_research_agent",
        return_value=SimpleNamespace(gather_initial_package=story_gather),
    )
    await stories._gather_initial_ideation_package(
        topic="UAE logistics",
        include_vidiq=True,
    )

    research_gather.assert_awaited_once()
    idea_gather.assert_awaited_once()
    story_gather.assert_awaited_once()
    assert research_gather.await_args.kwargs["include_vidiq"] is True
    assert idea_gather.await_args.kwargs["deep_max_uses"] == 2
    assert story_gather.await_args.kwargs["deep_max_uses"] == 2
    assert story_gather.await_args.kwargs["include_vidiq"] is True
