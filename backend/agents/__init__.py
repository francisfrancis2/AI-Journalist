"""Agent modules for the AI Journalist pipeline."""

from backend.agents.angles_and_hooks import AnglesAndHooksAgent
from backend.agents.chapter_writer import ChapterWriterAgent
from backend.agents.chief_editor_evaluator import ChiefEditorEvaluatorAgent
from backend.agents.research import ResearchAgent
from backend.agents.scriptwriter import ScriptwriterAgent

__all__ = [
    "ResearchAgent",
    "AnglesAndHooksAgent",
    "ChapterWriterAgent",
    "ScriptwriterAgent",
    "ChiefEditorEvaluatorAgent",
]
