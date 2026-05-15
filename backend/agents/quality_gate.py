"""
QualityGateAgent — rule-based gate for final script quality decisions.

After script_evaluator runs, this node:
  1. Tracks the best script seen across cycles.
  2. If the best script score is ≥ threshold → marks pipeline complete.
  3. If score is below threshold OR is a regression:
     - Restarts from researcher only when the audit shows genuine evidence gaps.
     - Otherwise surfaces the best revised script with a failure summary.
  4. Detects technical failures (API errors, empty research) and flags them for
     admin notification via is_technical_failure.
"""

from __future__ import annotations

import re
from typing import Optional

import structlog

from backend.config import settings
from backend.models.story import (
    FinalScript,
    ImprovementPlan,
    ScriptAuditReport,
)
from backend.models.research import EvaluationReport

log = structlog.get_logger(__name__)

# Keywords in error messages that indicate infrastructure / third-party API problems
_TECHNICAL_ERROR_PATTERNS = re.compile(
    r"(api[_ ]key|credit|rate.?limit|quota|timeout|connection|refused|"
    r"503|502|401|403|tavily|newsapi|alpha.?vantage|anthropic|aws|s3|postgres|neon)",
    re.IGNORECASE,
)

_GRADE_LABELS = {
    "A": "Excellent",
    "B": "Good",
    "C": "Needs improvement",
    "D": "Poor",
}


def _is_technical_failure(state: dict) -> bool:
    """Return True if the failure looks like an infrastructure / API problem."""
    error = state.get("error") or ""
    failed_node = state.get("failed_node") or ""
    research = state.get("research_package")
    # Empty research despite running the researcher is a telltale API failure sign
    source_count = len(research.sources) if research else 0

    if _TECHNICAL_ERROR_PATTERNS.search(error):
        return True
    if _TECHNICAL_ERROR_PATTERNS.search(failed_node):
        return True
    if state.get("research_iteration", 0) > 0 and source_count == 0:
        return True
    return False


def _build_improvement_plan(
    cycle_number: int,
    previous_score: float,
    audit: ScriptAuditReport,
    evaluation: Optional[EvaluationReport],
    is_regression: bool,
) -> ImprovementPlan:
    """
    Derive a concrete, targeted improvement plan from audit and evaluation data.

    Pulls the weakest criteria and section-level rewrite priorities so each
    downstream agent gets specific, actionable guidance rather than a blind restart.
    """
    # ── Identify weak criteria (below 0.65) ───────────────────────────────────
    criteria = audit.criteria
    criteria_scores = {
        "hook_strength": criteria.hook_strength,
        "narrative_flow": criteria.narrative_flow,
        "evidence_and_specificity": criteria.evidence_and_specificity,
        "pacing": criteria.pacing,
        "writing_quality": criteria.writing_quality,
        "production_readiness": criteria.production_readiness,
    }
    weak_criteria = [name for name, score in criteria_scores.items() if score < 0.65]

    # ── Research gaps: low evidence score → need more data ────────────────────
    research_gaps: list[str] = []
    if criteria.evidence_and_specificity < 0.65:
        research_gaps.append(
            "Find specific statistics, data points, and verifiable facts to support the narrative claims"
        )
    if evaluation and evaluation.improvement_suggestions:
        for suggestion in evaluation.improvement_suggestions[:3]:
            research_gaps.append(suggestion)
    # Collect distinct missing evidence from section weaknesses
    for section in audit.section_audits:
        for weakness in section.weaknesses:
            if any(kw in weakness.lower() for kw in ("statistic", "data", "source", "evidence", "fact", "number")):
                research_gaps.append(f"Section '{section.title}': {weakness}")
                break

    # ── Analysis focus: gaps the analyst should specifically address ──────────
    analysis_focus: list[str] = list(audit.weaknesses[:3])
    if evaluation and evaluation.weaknesses:
        analysis_focus.extend(evaluation.weaknesses[:2])
    if criteria.narrative_flow < 0.65:
        analysis_focus.append("Identify clearer cause-and-effect relationships between story segments")

    # ── Script directives: direct writing instructions for the scriptwriter ───
    script_directives: list[str] = list(audit.rewrite_priorities[:5])
    for section in audit.section_audits:
        if section.score < 0.60 and section.rewrite_recommendation:
            script_directives.append(
                f"Section '{section.title}': {section.rewrite_recommendation}"
            )
    if criteria.hook_strength < 0.65:
        script_directives.append(
            "Rewrite the opening hook — it must immediately establish a surprising or counterintuitive premise"
        )
    if criteria.pacing < 0.65:
        script_directives.append(
            "Tighten pacing: eliminate repetition and ensure each section advances the story"
        )

    # ── Failure reasons: plain-English summary ────────────────────────────────
    failure_reasons: list[str] = []
    if is_regression:
        failure_reasons.append(
            f"Score regressed to {previous_score:.0%} (quality got worse compared to previous cycle)"
        )
    if audit.overall_score < settings.script_audit_score_threshold:
        failure_reasons.append(
            f"Overall script grade: {audit.grade} ({audit.overall_score:.0%}) — below the 70% threshold"
        )
    for criterion in weak_criteria:
        label = criterion.replace("_", " ").title()
        score = criteria_scores[criterion]
        failure_reasons.append(f"{label}: {score:.0%}")

    return ImprovementPlan(
        cycle_number=cycle_number,
        previous_score=previous_score,
        research_gaps=research_gaps[:6],
        analysis_focus=analysis_focus[:5],
        script_directives=script_directives[:6],
        failure_reasons=failure_reasons[:8],
        is_regression=is_regression,
    )


def _script_has_source_shortfall(script: Optional[FinalScript]) -> bool:
    """Return True when the finished script is not sufficiently source-linked."""
    if script is None or not script.sections:
        return False

    if len(script.sources) < settings.min_sources_required:
        return True

    linked_sections = sum(1 for section in script.sections if section.source_ids)
    return (linked_sections / len(script.sections)) < 0.5


def _requires_research_restart(
    *,
    state: dict,
    audit: ScriptAuditReport,
    plan: ImprovementPlan,
    current_script: Optional[FinalScript],
    technical_failure: bool,
) -> bool:
    """
    Decide whether a full research restart is worth the time.

    Most below-threshold scripts should be fixed by script_rewriter before this
    gate runs. A full restart is reserved for missing evidence, weak sourcing,
    or explicit upstream research needs.
    """
    if technical_failure:
        return False

    if state.get("needs_more_research"):
        return True

    evidence_score = audit.criteria.evidence_and_specificity
    if evidence_score < 0.55 and plan.research_gaps:
        return True

    if evidence_score < 0.65 and _script_has_source_shortfall(current_script):
        return True

    research_terms = ("statistic", "data", "source", "evidence", "fact", "number", "verified")
    return evidence_score < 0.65 and any(
        any(term in gap.lower() for term in research_terms)
        for gap in plan.research_gaps
    )


def _build_failure_summary(
    plan: ImprovementPlan,
    best_score: float,
    cycles_run: int,
    technical: bool,
    rewrite_cycles: int = 0,
) -> str:
    reasons = "\n".join(f"• {r}" for r in plan.failure_reasons)
    cycle_word = "cycle" if cycles_run == 1 else "cycles"
    rewrite_clause = (
        f" and {rewrite_cycles} targeted script rewrite "
        f"{'pass' if rewrite_cycles == 1 else 'passes'}"
        if rewrite_cycles
        else ""
    )
    prefix = (
        "**Technical failure detected** — the pipeline could not complete due to "
        "infrastructure or API errors. Please contact your administrator.\n\n"
        if technical
        else ""
    )
    return (
        f"{prefix}"
        f"The AI Journalist pipeline ran {cycles_run} full research-and-writing {cycle_word}"
        f"{rewrite_clause} "
        f"but was unable to produce a script with a quality score above 70%. "
        f"The best result achieved was {best_score:.0%}.\n\n"
        f"**Reasons for failure:**\n{reasons}"
    )


class QualityGateAgent:
    """
    Rule-based gate that decides whether the pipeline has produced a passing script
    or should finish/restart with a targeted improvement plan.

    Returns a state patch with routing info in ``_quality_gate_route``.
    """

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
        passed = best_score >= settings.script_audit_score_threshold

        updates: dict = {
            "best_script": best_script,
            "best_script_score": best_score,
            "pipeline_cycle": new_cycle,
        }

        if passed:
            log.info(
                "quality_gate.passed",
                score=f"{best_score:.2f}",
                grade=audit.grade if audit else "?",
            )
            updates["pipeline_complete"] = True
            updates["final_script"] = best_script or current_script
            updates["_quality_gate_route"] = "done"
            return updates

        # ── Failed — prefer finishing with the best revised script unless more
        # research is genuinely required.
        technical = _is_technical_failure(state)
        plan = _build_improvement_plan(
            cycle_number=new_cycle,
            previous_score=current_score,
            audit=audit or ScriptAuditReport(criteria=_empty_criteria()),
            evaluation=evaluation,
            is_regression=is_regression,
        )

        can_restart_for_research = (
            audit is not None
            and new_cycle < settings.max_pipeline_cycles
            and _requires_research_restart(
                state=state,
                audit=audit,
                plan=plan,
                current_script=current_script,
                technical_failure=technical,
            )
        )

        if can_restart_for_research:
            # ── Restart with targeted research guidance ───────────────────────
            log.info(
                "quality_gate.restart_for_research",
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

        summary = _build_failure_summary(
            plan,
            best_score,
            new_cycle,
            technical,
            rewrite_cycles=state.get("script_revision_cycle", 0),
        )
        log.info(
            "quality_gate.finished_below_threshold",
            cycle=new_cycle,
            best_score=f"{best_score:.2f}",
            technical_failure=technical,
            research_gaps=len(plan.research_gaps),
            script_directives=len(plan.script_directives),
        )
        updates.update({
            "quality_improvement_plan": plan,
            "pipeline_failure_summary": summary,
            "is_technical_failure": technical,
            "pipeline_complete": True,
            # Surface the best script we have
            "final_script": best_script or current_script,
            "_quality_gate_route": "done",
        })
        return updates


def _empty_criteria():
    from backend.models.story import ScriptAuditCriteria
    return ScriptAuditCriteria()
