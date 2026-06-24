"""
LangGraph StateGraph definition for the AI Journalist multi-agent pipeline.

Pipeline stages:
  research_agent → angles_and_hooks → chapter_writer → chief_editor_evaluator
  → scriptwriter → chief_editor_script_audit → [chief_editor_rewrite | END]

Routing logic:
  - After chief editor plan review: pass recommendations directly to scriptwriter.
  - After chief editor script audit: if rewrite recommendations exist and rewrite budget
    remains → chief_editor_rewrite, otherwise → END.
"""

import structlog
from langgraph.graph import END, StateGraph

from backend.agents._research_enrichment import get_research_agent
from backend.agents.angles_and_hooks import AnglesAndHooksAgent
from backend.agents.chapter_writer import ChapterWriterAgent
from backend.agents.chief_editor_evaluator import ChiefEditorEvaluatorAgent
from backend.agents.scriptwriter import ScriptwriterAgent
from backend.config import settings
from backend.graph.state import JournalistState

log = structlog.get_logger(__name__)

# ── Instantiate agents (shared across graph invocations) ──────────────────────
# The Research Agent is shared with the writer-side enrichment helper so the
# pipeline research node and Chapter/Script enrichment reuse one instance.
_research_agent = get_research_agent()
_angles_and_hooks_agent = AnglesAndHooksAgent()
_chapter_writer_agent = ChapterWriterAgent()
_scriptwriter = ScriptwriterAgent()
_chief_editor = ChiefEditorEvaluatorAgent()


# ── Node functions ─────────────────────────────────────────────────────────────

async def researcher_node(state: JournalistState) -> dict:
    """Run the Research agent and update research artefacts."""
    log.info("graph.node.research_agent", story_id=state["story_id"])
    # Resume-after-angle-selection: research is already done → no-op.
    if state.get("research_package"):
        log.info("graph.node.research_agent.skipped_on_resume", story_id=state["story_id"])
        return {}
    try:
        updates = await _research_agent.run(state)
        return {**updates, "research_iteration": state["research_iteration"] + 1}
    except Exception as exc:
        log.error("graph.node.research_agent.error", error=str(exc))
        return {"error": str(exc), "failed_node": "research_agent"}


async def angles_and_hooks_node(state: JournalistState) -> dict:
    """Run Angles & Hooks analysis skill to synthesize research into direction."""
    log.info("graph.node.angles_and_hooks", story_id=state["story_id"])
    # Same idempotency as researcher_node: skip on resume after angle selection.
    if state.get("analysis_result"):
        log.info("graph.node.angles_and_hooks.skipped_on_resume", story_id=state["story_id"])
        return {}
    try:
        return await _angles_and_hooks_agent.analyze_research(state)
    except Exception as exc:
        log.error("graph.node.angles_and_hooks.error", error=str(exc))
        return {"error": str(exc), "failed_node": "angles_and_hooks"}


async def chapter_writer_node(state: JournalistState) -> dict:
    """Run the Chapter Writer agent to generate documentary structure proposals."""
    log.info("graph.node.chapter_writer", story_id=state["story_id"])
    try:
        return await _chapter_writer_agent.run(state)
    except Exception as exc:
        log.error("graph.node.chapter_writer.error", error=str(exc))
        return {"error": str(exc), "failed_node": "chapter_writer"}


async def evaluator_node(state: JournalistState) -> dict:
    """Run Chief Editor plan review and benchmark analytics skills."""
    log.info("graph.node.chief_editor_evaluator", story_id=state["story_id"])
    try:
        updates: dict = {"refinement_cycle": state["refinement_cycle"] + 1}
        updates.update(await _chief_editor.evaluate_story_plan(state))
        return updates
    except Exception as exc:
        log.error("graph.node.chief_editor_evaluator.error", error=str(exc))
        return {"error": str(exc), "failed_node": "chief_editor_evaluator"}


async def scriptwriter_node(state: JournalistState) -> dict:
    """Run the Scriptwriter agent to produce the final production-ready script."""
    log.info("graph.node.scriptwriter", story_id=state["story_id"])
    try:
        return await _scriptwriter.run(state)
    except Exception as exc:
        log.error("graph.node.scriptwriter.error", error=str(exc))
        return {"error": str(exc), "failed_node": "scriptwriter"}


async def chief_editor_script_audit_node(state: JournalistState) -> dict:
    """Run Chief Editor post-script audit. Fail open so the script is preserved."""
    log.info("graph.node.chief_editor_script_audit", story_id=state["story_id"])
    try:
        return await _chief_editor.audit_script(state)
    except Exception as exc:
        log.warning("graph.node.chief_editor_script_audit.error", error=str(exc))
        return {"script_audit_report": None}


async def chief_editor_rewrite_node(state: JournalistState) -> dict:
    """Run Chief Editor self-correction rewrite skill against audit feedback."""
    log.info("graph.node.chief_editor_rewrite", story_id=state["story_id"])
    try:
        return await _chief_editor.rewrite_script(state)
    except Exception as exc:
        log.error("graph.node.chief_editor_rewrite.error", error=str(exc))
        return {"error": str(exc), "failed_node": "chief_editor_rewrite"}


# ── Conditional routing ────────────────────────────────────────────────────────

def route_after_evaluator(state: JournalistState) -> str:
    """
    Decide next node after evaluation:
    - 'scriptwriter' -> chief editor recommendations are passed downstream
    - END           -> chief editor failed
    """
    if state.get("error"):
        return END

    return "scriptwriter"


def route_after_angles_and_hooks(state: JournalistState) -> str:
    """Pause for angle selection, or continue when an angle is already selected."""
    if state.get("error") or not state.get("analysis_result"):
        log.error("graph.route.angles_and_hooks_failed", story_id=state.get("story_id"), error=state.get("error"))
        return END
    if state.get("selected_angle"):
        return "chapter_writer"
    # No selection yet: pause. The API layer will relaunch the graph after the
    # user picks an angle via POST /stories/{id}/select-angle.
    log.info(
        "graph.route.awaiting_angle_selection",
        story_id=state.get("story_id"),
        generated=len(state.get("generated_angles") or []),
    )
    return END


def route_after_chapter_writer(state: JournalistState) -> str:
    """Route to chief editor, or END early if chapter writer failed."""
    if state.get("error") or not state.get("selected_storyline"):
        log.error(
            "graph.route.chapter_writer_failed",
            story_id=state.get("story_id"),
            error=state.get("error"),
        )
        return END
    return "chief_editor_evaluator"


def route_after_chief_editor_script_audit(state: JournalistState) -> str:
    """
    Trigger a targeted script rewrite when audit recommendations exist and
    rewrite budget remains; otherwise finish.
    """
    if state.get("error"):
        return END

    audit = state.get("script_audit_report")
    if audit is None or state.get("final_script") is None:
        return END

    recommendations = state.get("script_rewrite_recommendations") or audit.rewrite_priorities
    revision_cycle = state.get("script_revision_cycle", 0)
    if recommendations and revision_cycle < settings.max_script_revision_cycles:
        log.info(
            "graph.route.script_rewrite",
            story_id=state.get("story_id"),
            recommendations=len(recommendations),
            revision_cycle=revision_cycle,
        )
        return "chief_editor_rewrite"

    return END


def route_after_researcher(state: JournalistState) -> str:
    """Always continue to Angles & Hooks after research (error guard only)."""
    if state.get("error"):
        return END
    return "angles_and_hooks"


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_journalist_graph() -> StateGraph:
    """
    Assemble and compile the LangGraph StateGraph for the journalist pipeline.

    Returns:
        A compiled LangGraph application ready for ainvoke / astream.
    """
    graph = StateGraph(JournalistState)

    # Register nodes
    graph.add_node("research_agent", researcher_node)
    graph.add_node("angles_and_hooks", angles_and_hooks_node)
    graph.add_node("chapter_writer", chapter_writer_node)
    graph.add_node("chief_editor_evaluator", evaluator_node)
    graph.add_node("scriptwriter", scriptwriter_node)
    graph.add_node("chief_editor_script_audit", chief_editor_script_audit_node)
    graph.add_node("chief_editor_rewrite", chief_editor_rewrite_node)

    # Entry point
    graph.set_entry_point("research_agent")

    # Fixed edges
    graph.add_conditional_edges("research_agent", route_after_researcher, {
        "angles_and_hooks": "angles_and_hooks",
        END: END,
    })
    graph.add_conditional_edges("angles_and_hooks", route_after_angles_and_hooks, {
        "chapter_writer": "chapter_writer",
        END: END,
    })
    graph.add_conditional_edges("chapter_writer", route_after_chapter_writer, {
        "chief_editor_evaluator": "chief_editor_evaluator",
        END: END,
    })

    # Conditional routing after evaluation
    graph.add_conditional_edges(
        "chief_editor_evaluator",
        route_after_evaluator,
        {
            "scriptwriter": "scriptwriter",
            END: END,
        },
    )

    graph.add_edge("scriptwriter", "chief_editor_script_audit")
    graph.add_conditional_edges("chief_editor_script_audit", route_after_chief_editor_script_audit, {
        "chief_editor_rewrite": "chief_editor_rewrite",
        END: END,
    })
    graph.add_edge("chief_editor_rewrite", "chief_editor_script_audit")

    return graph.compile()


# Module-level compiled graph — import this in API routes
journalist_graph = build_journalist_graph()
