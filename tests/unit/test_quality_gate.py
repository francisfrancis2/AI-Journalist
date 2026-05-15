import uuid
from types import SimpleNamespace

import pytest

from backend.agents.quality_gate import QualityGateAgent
from backend.models.story import (
    FinalScript,
    ScriptAuditCriteria,
    ScriptAuditReport,
    ScriptSection,
)


def _script(*, source_ids: list[str], sources: list[dict] | None = None) -> FinalScript:
    return FinalScript(
        story_id=uuid.uuid4(),
        title="The Test Story",
        logline="A test documentary.",
        opening_hook="A sharp question opens the story.",
        sections=[
            ScriptSection(
                section_number=1,
                title="Opening",
                narration="The opening narration.",
                estimated_seconds=90,
                source_ids=source_ids,
            ),
            ScriptSection(
                section_number=2,
                title="Middle",
                narration="The middle narration.",
                estimated_seconds=120,
                source_ids=source_ids,
            ),
        ],
        closing_statement="The closing statement.",
        total_word_count=100,
        estimated_duration_minutes=1.0,
        sources=sources or [
            {"source_id": sid, "title": f"Source {sid}", "credibility": "high"}
            for sid in source_ids
        ],
    )


def _audit(**scores: float) -> ScriptAuditReport:
    report = ScriptAuditReport(
        criteria=ScriptAuditCriteria(
            hook_strength=scores.get("hook_strength", 0.7),
            narrative_flow=scores.get("narrative_flow", 0.7),
            evidence_and_specificity=scores.get("evidence_and_specificity", 0.7),
            pacing=scores.get("pacing", 0.7),
            writing_quality=scores.get("writing_quality", 0.7),
            production_readiness=scores.get("production_readiness", 0.7),
        ),
        audit_summary="Audit summary.",
        weaknesses=["Weakness"],
        rewrite_priorities=["Rewrite the weak section."],
    )
    report.compute_overall()
    return report


@pytest.mark.asyncio
async def test_quality_gate_finishes_after_rewrite_when_problem_is_not_research():
    script = _script(source_ids=["source-1", "source-2", "source-3", "source-4", "source-5"])
    audit = _audit(
        hook_strength=0.68,
        narrative_flow=0.64,
        evidence_and_specificity=0.74,
        pacing=0.58,
        writing_quality=0.42,
        production_readiness=0.55,
    )

    result = await QualityGateAgent().run({
        "story_id": str(script.story_id),
        "final_script": script,
        "script_audit_report": audit,
        "evaluation_report": None,
        "pipeline_cycle": 0,
        "best_script": None,
        "best_script_score": 0.0,
        "script_revision_cycle": 1,
        "needs_more_research": False,
        "research_iteration": 1,
        "research_package": SimpleNamespace(sources=[object()] * 5),
        "error": None,
        "failed_node": None,
    })

    assert result["_quality_gate_route"] == "done"
    assert result["pipeline_complete"] is True
    assert result["final_script"] == script
    assert "targeted script rewrite pass" in result["pipeline_failure_summary"]


@pytest.mark.asyncio
async def test_quality_gate_restarts_only_for_evidence_shortfall():
    script = _script(source_ids=[], sources=[])
    audit = _audit(
        hook_strength=0.72,
        narrative_flow=0.68,
        evidence_and_specificity=0.30,
        pacing=0.66,
        writing_quality=0.72,
        production_readiness=0.65,
    )

    result = await QualityGateAgent().run({
        "story_id": str(script.story_id),
        "final_script": script,
        "script_audit_report": audit,
        "evaluation_report": None,
        "pipeline_cycle": 0,
        "best_script": None,
        "best_script_score": 0.0,
        "script_revision_cycle": 1,
        "needs_more_research": False,
        "research_iteration": 1,
        "research_package": SimpleNamespace(sources=[object()] * 5),
        "error": None,
        "failed_node": None,
    })

    assert result["_quality_gate_route"] == "restart"
    assert result["pipeline_complete"] is False
    assert result["final_script"] is None
    assert result["quality_improvement_plan"].research_gaps


@pytest.mark.asyncio
async def test_quality_gate_passes_with_best_script_even_if_latest_regresses():
    best_script = _script(source_ids=["source-1", "source-2", "source-3", "source-4", "source-5"])
    latest_script = _script(source_ids=["source-1", "source-2", "source-3", "source-4", "source-5"])
    latest_audit = _audit(
        hook_strength=0.70,
        narrative_flow=0.70,
        evidence_and_specificity=0.70,
        pacing=0.70,
        writing_quality=0.70,
        production_readiness=0.70,
    )

    result = await QualityGateAgent().run({
        "story_id": str(latest_script.story_id),
        "final_script": latest_script,
        "script_audit_report": latest_audit,
        "evaluation_report": None,
        "pipeline_cycle": 1,
        "best_script": best_script,
        "best_script_score": 0.74,
        "script_revision_cycle": 1,
        "needs_more_research": False,
        "research_iteration": 1,
        "research_package": SimpleNamespace(sources=[object()] * 5),
        "error": None,
        "failed_node": None,
    })

    assert result["_quality_gate_route"] == "done"
    assert result["pipeline_complete"] is True
    assert result["final_script"] == best_script
