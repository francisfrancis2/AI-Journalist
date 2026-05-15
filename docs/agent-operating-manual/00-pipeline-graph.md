# Pipeline Graph

**Source file:** `backend/graph/journalist_graph.py`

LangGraph StateGraph definition for the AI Journalist multi-agent pipeline.

Pipeline stages:
  researcher → analyst → storyline_creator → evaluator → [scriptwriter | researcher]
  scriptwriter → script_evaluator → quality_gate → [researcher (restart) | END]

Routing logic:
  - After evaluator: if approved → scriptwriter, else if cycles < max → storyline_creator,
    else if needs_more_research → researcher
  - After quality_gate: if score ≥ 70% and improving → END, else restart from researcher
    with ImprovementPlan; after max_pipeline_cycles → END with failure summary

### Routing And Assembly Logic

```python
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
```

```python
def route_after_analyst(state: JournalistState) -> str:
    """Proceed to storyline_creator, or END early if analyst failed without a result."""
    if state.get("error") or not state.get("analysis_result"):
        log.error("graph.route.analyst_failed", story_id=state.get("story_id"), error=state.get("error"))
        return END
    return "storyline_creator"
```

```python
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
```

```python
def route_after_quality_gate(state: JournalistState) -> str:
    """Route based on the quality gate decision embedded in state."""
    route = state.get("_quality_gate_route", "done")
    if route == "restart":
        return "researcher"
    return END
```

```python
def route_after_researcher(state: JournalistState) -> str:
    """Always continue to analyst after research (error guard only)."""
    if state.get("error"):
        return END
    return "analyst"
```

```python
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
    graph.add_node("quality_gate", quality_gate_node)

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
            "storyline_creator": "storyline_creator",
            "researcher": "researcher",
            END: END,
        },
    )

    graph.add_edge("scriptwriter", "script_evaluator")
    graph.add_edge("script_evaluator", "quality_gate")
    graph.add_conditional_edges("quality_gate", route_after_quality_gate, {
        "researcher": "researcher",
        END: END,
    })

    return graph.compile()
```
