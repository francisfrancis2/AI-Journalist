## Quality Gate Agent

**Source file:** `backend/agents/quality_gate.py`

### Responsibilities

QualityGateAgent — rule-based gate that controls full pipeline restart cycles.

After script_evaluator runs, this node:
  1. Tracks the best script seen across cycles.
  2. If the new score is ≥ threshold AND improving → marks pipeline complete.
  3. If score is below threshold OR is a regression:
     - Below max cycles: builds a targeted ImprovementPlan and restarts from researcher.
     - At max cycles: surfaces the best script with a failure summary.
  4. Detects technical failures (API errors, empty research) and flags them for
     admin notification via is_technical_failure.

### Agent Classes

- `QualityGateAgent`

### Main Methods

- `QualityGateAgent.async def run(self, state: dict)`

### System Prompt

This agent does not use an LLM system prompt.

### Run Logic

```python
async def run(self, state: dict) -> dict:  # noqa: C901
        audit: Optional[ScriptAuditReport] = state.get("script_audit_report")
        current_script: Optional[FinalScript] = state.get("final_script")
        evaluation: Optional[EvaluationReport] = state.get("evaluation_report")

        current_score = audit.overall_score if audit else 0.0
        best_score = state.get("best_script_score", 0.0)
        best_script = state.get("best_script")
        pipeline_cycle: int = state.get("pipeline_cycle", 0)

        log.info(
            "quality_gate.evaluate",
            story_id=state.get("story_id"),
            current_score=f"{current_score:.2f}",
            best_score=f"{best_score:.2f}",
            pipeline_cycle=pipeline_cycle,
            threshold=settings.script_audit_score_threshold,
        )

        # ── Update best-script tracker ────────────────────────────────────────
        if current_score > best_score and current_script is not None:
            best_script = current_script
            best_score = current_score

        new_cycle = pipeline_cycle + 1
        is_regression = (
            pipeline_cycle > 0  # not the first run
            and current_score < best_score  # strictly worse than the best we've seen
        )
        passed = (
            current_score >= settings.script_audit_score_threshold
            and not is_regression
        )

        updates: dict = {
            "best_script": best_script,
            "best_script_score": best_score,
            "pipeline_cycle": new_cycle,
        }

        if passed:
            log.info(
                "quality_gate.passed",
                score=f"{current_score:.2f}",
                grade=audit.grade if audit else "?",
            )
            updates["pipeline_complete"] = True
            updates["_quality_gate_route"] = "done"
            return updates

        # ── Failed — decide whether to restart or give up ─────────────────────
        if new_cycle >= settings.max_pipeline_cycles:
            technical = _is_technical_failure(state)
            plan = _build_improvement_plan(
                cycle_number=new_cycle,
                previous_score=current_score,
                audit=audit or ScriptAuditReport(criteria=_empty_criteria()),
                evaluation=evaluation,
                is_regression=is_regression,
            )
            summary = _build_failure_summary(plan, best_score, new_cycle, technical)

            log.warning(
                "quality_gate.max_cycles_reached",
                cycles=new_cycle,
                best_score=f"{best_score:.2f}",
                technical_failure=technical,
            )
            updates.update({
                "pipeline_failure_summary": summary,
                "is_technical_failure": technical,
                "pipeline_complete": True,
                # Surface the best script we have
                "final_script": best_script or current_script,
                "_quality_gate_route": "done",
            })
            return updates

        # ── Restart with targeted improvement plan ────────────────────────────
        plan = _build_improvement_plan(
            cycle_number=new_cycle,
            previous_score=current_score,
            audit=audit or ScriptAuditReport(criteria=_empty_criteria()),
            evaluation=evaluation,
            is_regression=is_regression,
        )
        log.info(
            "quality_gate.restart",
            cycle=new_cycle,
            research_gaps=len(plan.research_gaps),
            script_directives=len(plan.script_directives),
        )
        updates.update({
            "quality_improvement_plan": plan,
            "pipeline_complete": False,
            # Reset per-cycle counters so downstream agents run fresh
            "research_iteration": 0,
            "refinement_cycle": 0,
            "script_revision_cycle": 0,
            "approved_for_scripting": False,
            "needs_more_research": False,
            "final_script": None,
            "script_audit_report": None,
            "_quality_gate_route": "restart",
        })
        return updates
```
