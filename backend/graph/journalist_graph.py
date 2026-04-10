"""
LangGraph StateGraph definition for the AI Journalist multi-agent pipeline.

Pipeline stages:
  researcher → analyst → storyline_creator → evaluator → [scriptwriter | researcher]

Routing logic:
  - After evaluator: if approved → scriptwriter, else if cycles < max → storyline_creator,
    else if needs_more_research → researcher
  - After researcher: if iteration < max → analyst, else → storyline_creator (best effort)
"""

import asyncio

import structlog
from langgraph.graph import END, StateGraph

from backend.agents.analyst import AnalystAgent
from backend.agents.benchmarker import BenchmarkAgent
from backend.agents.evaluator import EvaluatorAgent
from backend.agents.researcher import ResearcherAgent
from backend.agents.scriptwriter import ScriptwriterAgent
from backend.agents.storyline_creator import StorylineCreatorAgent
from backend.config import settings
from backend.graph.state import JournalistState

log = structlog.get_logger(__name__)

# ── Instantiate agents (shared across graph invocations) ──────────────────────
_researcher = ResearcherAgent()
_analyst = AnalystAgent()
_storyline_creator = StorylineCreatorAgent()
_evaluator = EvaluatorAgent()
_benchmarker = BenchmarkAgent()
_scriptwriter = ScriptwriterAgent()


# ── Node functions ─────────────────────────────────────────────────────────────

async def researcher_node(state: JournalistState) -> dict:
    """Run the Researcher agent and update research artefacts."""
    log.info("graph.node.researcher", story_id=state["story_id"])
    try:
        updates = await _researcher.run(state)
        return {**updates, "research_iteration": state["research_iteration"] + 1}
    except Exception as exc:
        log.error("graph.node.researcher.error", error=str(exc))
        return {"error": str(exc), "failed_node": "researcher"}


async def analyst_node(state: JournalistState) -> dict:
    """Run the Analyst agent to synthesise research into structured findings."""
    log.info("graph.node.analyst", story_id=state["story_id"])
    try:
        return await _analyst.run(state)
    except Exception as exc:
        log.error("graph.node.analyst.error", error=str(exc))
        return {"error": str(exc), "failed_node": "analyst"}


async def storyline_creator_node(state: JournalistState) -> dict:
    """Run the Storyline Creator agent to generate documentary structure proposals."""
    log.info("graph.node.storyline_creator", story_id=state["story_id"])
    try:
        return await _storyline_creator.run(state)
    except Exception as exc:
        log.error("graph.node.storyline_creator.error", error=str(exc))
        return {"error": str(exc), "failed_node": "storyline_creator"}


async def evaluator_node(state: JournalistState) -> dict:
    """Run the Evaluator and BenchmarkAgent in parallel, then merge results."""
    log.info("graph.node.evaluator", story_id=state["story_id"])
    try:
        eval_result, bench_result = await asyncio.gather(
            _evaluator.run(state),
            _benchmarker.run(state),
            return_exceptions=True,
        )
        updates: dict = {"refinement_cycle": state["refinement_cycle"] + 1}

        if isinstance(eval_result, Exception):
            log.error("graph.node.evaluator.error", error=str(eval_result))
            return {"error": str(eval_result), "failed_node": "evaluator"}
        updates.update(eval_result)

        if isinstance(bench_result, Exception):
            log.warning("graph.node.benchmarker.error", error=str(bench_result))
        else:
            updates.update(bench_result)

        return updates
    except Exception as exc:
        log.error("graph.node.evaluator.error", error=str(exc))
        return {"error": str(exc), "failed_node": "evaluator"}


async def scriptwriter_node(state: JournalistState) -> dict:
    """Run the Scriptwriter agent to produce the final production-ready script."""
    log.info("graph.node.scriptwriter", story_id=state["story_id"])
    try:
        updates = await _scriptwriter.run(state)
        return {**updates, "pipeline_complete": True}
    except Exception as exc:
        log.error("graph.node.scriptwriter.error", error=str(exc))
        return {"error": str(exc), "failed_node": "scriptwriter"}


# ── Conditional routing ────────────────────────────────────────────────────────

def route_after_evaluator(state: JournalistState) -> str:
    """
    Decide next node after evaluation:
    - 'scriptwriter'        → quality threshold met
    - 'storyline_creator'   → needs refinement, cycles remaining
    - 'researcher'          → needs more data
    - END                   → max cycles exhausted, exit with best effort
    """
    if state.get("error"):
        return END

    if state.get("approved_for_scripting"):
        return "scriptwriter"

    if state["refinement_cycle"] < settings.max_refinement_cycles:
        if state.get("needs_more_research") and state["research_iteration"] < settings.max_research_iterations:
            return "researcher"
        return "storyline_creator"

    # Max refinement cycles reached — write what we have
    log.warning(
        "graph.route.max_refinement_reached",
        story_id=state["story_id"],
        score=state["evaluation_report"].overall_score if state.get("evaluation_report") else 0,
    )
    return "scriptwriter"


def route_after_storyline_creator(state: JournalistState) -> str:
    """Route to evaluator, or END early if storyline_creator failed."""
    if state.get("error") or not state.get("selected_storyline"):
        log.error(
            "graph.route.storyline_creator_failed",
            story_id=state.get("story_id"),
            error=state.get("error"),
        )
        return END
    return "evaluator"


def route_after_researcher(state: JournalistState) -> str:
    """Always continue to analyst after research (error guard only)."""
    if state.get("error"):
        return END
    return "analyst"


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_journalist_graph() -> StateGraph:
    """
    Assemble and compile the LangGraph StateGraph for the journalist pipeline.

    Returns:
        A compiled LangGraph application ready for ainvoke / astream.
    """
    graph = StateGraph(JournalistState)

    # Register nodes
    graph.add_node("researcher", researcher_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("storyline_creator", storyline_creator_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("scriptwriter", scriptwriter_node)

    # Entry point
    graph.set_entry_point("researcher")

    # Fixed edges
    graph.add_conditional_edges("researcher", route_after_researcher, {
        "analyst": "analyst",
        END: END,
    })
    graph.add_edge("analyst", "storyline_creator")
    graph.add_conditional_edges("storyline_creator", route_after_storyline_creator, {
        "evaluator": "evaluator",
        END: END,
    })

    # Conditional routing after evaluation
    graph.add_conditional_edges(
        "evaluator",
        route_after_evaluator,
        {
            "scriptwriter": "scriptwriter",
            "storyline_creator": "storyline_creator",
            "researcher": "researcher",
            END: END,
        },
    )

    # Terminal edge
    graph.add_edge("scriptwriter", END)

    return graph.compile()


# Module-level compiled graph — import this in API routes
journalist_graph = build_journalist_graph()
