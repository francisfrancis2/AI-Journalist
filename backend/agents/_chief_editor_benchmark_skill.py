"""
Chief Editor Benchmark Skill — scores a generated storyline against the benchmark pattern library.

Runs inside ChiefEditorEvaluatorAgent after chapter/story structure creation.
Requires the benchmark corpus to be built first.
"""

import json

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.models.benchmark import BenchmarkReport, BenchmarkScores, BIPatternLibrary
from backend.models.research import StorylineProposal
from backend.services.benchmarking import load_active_benchmark_library
from backend.services.duration_targets import duration_prompt_block, duration_target_for
from backend.services.prompt_loader import load_prompt

log = structlog.get_logger(__name__)



class BenchmarkSkill:
    """
    Scores a generated storyline against the benchmark pattern library.

    Loads the pattern library from the local JSON cache on first use.
    Falls back gracefully if no corpus has been built yet.

    Example::

        skill = BenchmarkSkill()
        result = await agent.run(state)
    """

    def __init__(self) -> None:
        _llm = ChatAnthropic(
            model=settings.claude_haiku_model,
            api_key=settings.anthropic_api_key,
            max_tokens=2500,
            temperature=0.1,
        )
        self._structured_llm = _llm.with_structured_output(BenchmarkScores)

    def _build_prompt(self, storyline: StorylineProposal, library: BIPatternLibrary, state: dict) -> str:
        duration_target = duration_target_for(state.get("target_duration_minutes"))
        acts_text = "\n".join(
            f"  Act {a.act_number} ({a.estimated_duration_seconds}s): {a.act_title}\n"
            f"    Purpose: {a.purpose}\n"
            f"    Key points: {', '.join(a.key_points[:4])}"
            for a in storyline.acts
        )
        sample_hooks = "\n".join(f"  - {h}" for h in library.sample_hooks[:5])

        return (
            f"=== GENERATED STORYLINE ===\n"
            f"Title: {storyline.title}\n"
            f"Logline: {storyline.logline}\n"
            f"Opening Hook: {storyline.opening_hook}\n"
            f"Closing Statement: {storyline.closing_statement}\n"
            f"{duration_prompt_block(duration_target, role='Chief Editor Benchmark')}"
            f"Requested act count range: {duration_target.act_count_label}; "
            f"actual act count: {len(storyline.acts)}.\n"
            f"Total Duration: {storyline.total_estimated_duration_seconds}s "
            f"({storyline.total_estimated_duration_seconds // 60} min)\n\n"
            f"Acts ({len(storyline.acts)} total):\n{acts_text}\n\n"
            f"=== BENCHMARK PATTERN LIBRARY (from {library.doc_count} docs) ===\n"
            f"Avg act count: {library.avg_act_count:.1f}\n"
            f"Avg act duration: {library.avg_act_duration_seconds:.0f}s\n"
            f"Avg stats per doc: {library.avg_stat_count:.1f}\n"
            f"Human story typically at act: {library.human_story_act_avg:.1f}\n"
            f"Hook type distribution: {json.dumps(library.hook_type_distribution)}\n"
            f"Closing device distribution: {json.dumps(library.closing_device_distribution)}\n"
            f"Title formula distribution: {json.dumps(library.title_formula_distribution)}\n\n"
            f"Sample opening hooks:\n{sample_hooks}"
        )

    async def run(self, state: dict) -> dict:
        """
        Score the selected storyline against benchmark patterns.

        Returns:
            Partial state update with ``benchmark_report``.
            If no corpus exists, returns empty benchmark_report with a warning.
        """
        storyline: StorylineProposal = state["selected_storyline"]
        topic: str = state["topic"]

        log.info("chief_editor.benchmark.start", topic=topic, title=storyline.title)

        library, library_status = await load_active_benchmark_library()
        if not library or not library_status.ready_for_scoring:
            log.warning(
                "chief_editor.benchmark.skipped",
                reason="Benchmark corpus is not ready for scoring",
                notes=library_status.notes,
            )
            return {"benchmark_report": None}

        system = load_prompt("chief_editor_evaluator")

        scores: BenchmarkScores = await self._structured_llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=self._build_prompt(storyline, library, state)),
        ])

        report = BenchmarkReport.from_scores(scores)
        report.library_key = library_status.key
        report.library_label = library_status.label
        report.library_version = library_status.version
        report.reference_doc_count = library_status.doc_count
        report.built_at = library_status.built_at
        report.stale = library_status.stale
        report.status_notes = library_status.notes

        log.info(
            "chief_editor.benchmark.complete",
            topic=topic,
            benchmark_score=f"{report.bi_similarity_score:.2f}",
            grade=report.grade,
        )

        return {"benchmark_report": report}
