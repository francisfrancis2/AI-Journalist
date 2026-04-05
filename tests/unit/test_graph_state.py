"""
Unit tests for the LangGraph state definition and factory function.
"""

import uuid

import pytest

from backend.graph.state import JournalistState, create_initial_state
from backend.models.story import StoryTone


class TestCreateInitialState:
    def test_defaults(self, sample_topic):
        state = create_initial_state(topic=sample_topic)
        assert state["topic"] == sample_topic
        assert state["tone"] == StoryTone.EXPLANATORY
        assert state["research_iteration"] == 0
        assert state["refinement_cycle"] == 0
        assert state["needs_more_research"] is False
        assert state["approved_for_scripting"] is False
        assert state["pipeline_complete"] is False
        assert state["research_package"] is None
        assert state["analysis_result"] is None
        assert state["selected_storyline"] is None
        assert state["final_script"] is None
        assert state["error"] is None

    def test_custom_story_id(self, sample_topic):
        custom_id = str(uuid.uuid4())
        state = create_initial_state(topic=sample_topic, story_id=custom_id)
        assert state["story_id"] == custom_id

    def test_generates_story_id_if_none(self, sample_topic):
        state = create_initial_state(topic=sample_topic)
        # Must be a valid UUID string
        parsed = uuid.UUID(state["story_id"])
        assert str(parsed) == state["story_id"]

    def test_custom_tone(self, sample_topic):
        state = create_initial_state(topic=sample_topic, tone=StoryTone.INVESTIGATIVE)
        assert state["tone"] == StoryTone.INVESTIGATIVE

    def test_empty_messages(self, sample_topic):
        state = create_initial_state(topic=sample_topic)
        assert state["messages"] == []

    def test_empty_storyline_proposals(self, sample_topic):
        state = create_initial_state(topic=sample_topic)
        assert state["storyline_proposals"] == []
