"""Chief Editor & Evaluator Agent.

Evaluation, benchmark analytics, audit, and self-correction live here as skills
inside one editorial agent rather than separate workflow agents.
"""

import asyncio
from typing import Any

import structlog

from backend.agents._chief_editor_benchmark_skill import BenchmarkSkill
from backend.agents._chief_editor_plan_review_skill import PlanReviewSkill
from backend.agents._chief_editor_script_audit_skill import ScriptAuditSkill
from backend.agents._chief_editor_script_rewrite_skill import ScriptRewriteSkill

log = structlog.get_logger(__name__)


class ChiefEditorEvaluatorAgent:
    """Canonical reviewer/editor agent for the five-agent workflow."""

    def __init__(self) -> None:
        self._plan_review = PlanReviewSkill()
        self._benchmark = BenchmarkSkill()
        self._script_audit = ScriptAuditSkill()
        self._script_rewrite = ScriptRewriteSkill()

    async def evaluate_story_plan(self, state: dict[str, Any]) -> dict[str, Any]:
        """Evaluate chapter/storyline quality and attach benchmark analytics."""
        eval_result, bench_result = await asyncio.gather(
            self._plan_review.run(state),
            self._benchmark.run(state),
            return_exceptions=True,
        )

        if isinstance(eval_result, Exception):
            raise eval_result

        updates: dict[str, Any] = dict(eval_result)
        if isinstance(bench_result, Exception):
            log.warning("chief_editor.benchmark_skill_failed", error=str(bench_result))
        else:
            updates.update(bench_result)
        return updates

    async def audit_script(self, state: dict[str, Any]) -> dict[str, Any]:
        """Evaluate the finished script and produce rewrite priorities."""
        return await self._script_audit.run(state)

    async def rewrite_script(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run the self-correction rewrite skill against audit feedback."""
        return await self._script_rewrite.run(state)

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Default graph behavior: pre-script story plan review."""
        return await self.evaluate_story_plan(state)
