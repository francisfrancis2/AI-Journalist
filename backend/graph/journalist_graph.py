"""
LangGraph StateGraph definition for the AI Journalist multi-agent pipeline.

Pipeline stages:
  researcher → analyst → storyline_creator → evaluator
  → scriptwriter → script_evaluator → [script_rewriter | END]

Routing logic:
  - After evaluator: pass recommendations directly to scriptwriter.
  - After script_evaluator: if rewrite recommendations exist and rewrite budget remains
    → script_rewriter, otherwise → END.
"""

import asyncio

import structlog
from langgraph.graph import END, StateGraph

from backend.agents.analyst import AnalystAgent
from backend.agents.benchmarker import BenchmarkAgent
from backend.agents.evaluator import EvaluatorAgent
from backend.agents.researcher import ResearcherAgent
from backend.agents.script_evaluator import ScriptEvaluatorAgent
from backend.agents.script_rewriter import ScriptRewriterAgent
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
_script_evaluator = ScriptEvaluatorAgent()
_script_rewriter = ScriptRewriterAgent()


# ── Node functions ─────────────────────────────────────────────────────────────

async def researcher_node(state: JournalistState) -> dict:
    """Run the Researcher agent and update research artefacts."""
    log.info("graph.node.researcher", story_id=state["story_id"])
    # Resume-after-angle-selection: research is already done → no-op.
    if state.get("research_package"):
        log.info("graph.node.researcher.skipped_on_resume", story_id=state["story_id"])
        return {}
    try:
        updates = await _researcher.run(state)
        return {**updates, "research_iteration": state["research_iteration"] + 1}
    except Exception as exc:
        log.error("graph.node.researcher.error", error=str(exc))
        return {"error": str(exc), "failed_node": "researcher"}


async def analyst_node(state: JournalistState) -> dict:
    """Run the Analyst agent to synthesise research into structured findings."""
    log.info("graph.node.analyst", story_id=state["story_id"])
    # Same idempotency as researcher_node: skip on resume after angle selection.
    if state.get("analysis_result"):
        log.info("graph.node.analyst.skipped_on_resume", story_id=state["story_id"])
        return {}
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
        return await _scriptwriter.run(state)
    except Exception as exc:
        log.error("graph.node.scriptwriter.error", error=str(exc))
        return {"error": str(exc), "failed_node": "scriptwriter"}


async def script_evaluator_node(state: JournalistState) -> dict:
    """Run the post-script evaluator. Fail open so the completed script is preserved."""
    log.info("graph.node.script_evaluator", story_id=state["story_id"])
    try:
        return await _script_evaluator.run(state)
    except Exception as exc:
        log.warning("graph.node.script_evaluator.error", error=str(exc))
        return {"script_audit_report": None}


async def script_rewriter_node(state: JournalistState) -> dict:
    """Run a targeted rewrite pass against the post-script audit feedback."""
    log.info("graph.node.script_rewriter", story_id=state["story_id"])
    try:
        return await _script_rewriter.run(state)
    except Exception as exc:
        log.error("graph.node.script_rewriter.error", error=str(exc))
        return {"error": str(exc), "failed_node": "script_rewriter"}


# ── Conditional routing ────────────────────────────────────────────────────────

def route_after_evaluator(state: JournalistState) -> str:
    """
    Decide next node after evaluation:
    - 'scriptwriter' → evaluator recommendations are passed downstream
    - END            → evaluator failed
    """
    if state.get("error"):
        return END

    return "scriptwriter"


def route_after_analyst(state: JournalistState) -> str:
    """Pause for angle selection, or continue when an angle is already selected."""
    if state.get("error") or not state.get("analysis_result"):
        log.error("graph.route.analyst_failed", story_id=state.get("story_id"), error=state.get("error"))
        return END
    if state.get("selected_angle"):
        return "storyline_creator"
    # No selection yet: pause. The API layer will relaunch the graph after the
    # user picks an angle via POST /stories/{id}/select-angle.
    log.info(
        "graph.route.awaiting_angle_selection",
        story_id=state.get("story_id"),
        generated=len(state.get("generated_angles") or []),
    )
    return END


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


def route_after_script_evaluator(state: JournalistState) -> str:
    """
    Trigger a targeted script rewrite when audit recommendations exist and
    rewrite budget remains; otherwise finish.
    """
    if state.get("error"):
        return END

    audit = state.get("script_audit_report")
    if audit is None or state.get("final_script") is None:
        return END

    recommendations = state.get("script_rewriter_recommendations") or audit.rewrite_priorities
    revision_cycle = state.get("script_revision_cycle", 0)
    if recommendations and revision_cycle < settings.max_script_revision_cycles:
        log.info(
            "graph.route.script_rewrite",
            story_id=state.get("story_id"),
            recommendations=len(recommendations),
            revision_cycle=revision_cycle,
        )
        return "script_rewriter"

    return END


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
    graph.add_node("script_evaluator", script_evaluator_node)
    graph.add_node("script_rewriter", script_rewriter_node)

    # Entry point
    graph.set_entry_point("researcher")

    # Fixed edges
    graph.add_conditional_edges("researcher", route_after_researcher, {
        "analyst": "analyst",
        END: END,
    })
    graph.add_conditional_edges("analyst", route_after_analyst, {
        "storyline_creator": "storyline_creator",
        END: END,
    })
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
            END: END,
        },
    )

    graph.add_edge("scriptwriter", "script_evaluator")
    graph.add_conditional_edges("script_evaluator", route_after_script_evaluator, {
        "script_rewriter": "script_rewriter",
        END: END,
    })
    graph.add_edge("script_rewriter", "script_evaluator")

    return graph.compile()


# Module-level compiled graph — import this in API routes
journalist_graph = build_journalist_graph()
