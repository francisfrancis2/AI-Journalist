"""
BenchmarkAgent — scores a generated storyline against the BI pattern library.

Runs in parallel with the EvaluatorAgent after storyline creation.
Requires the BI pattern library to be built first via build_corpus.py.
"""

import json
from pathlib import Path
from typing import Optional

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.models.benchmark import BenchmarkReport, BenchmarkScores, BIPatternLibrary
from backend.models.research import StorylineProposal

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a documentary quality benchmarker who scores storylines against
Business Insider YouTube documentary patterns.

You will be given:
1. A generated documentary storyline
2. The BI pattern library (extracted from {doc_count} real BI documentaries)

Score the storyline against each BI benchmark criterion from 0.0 to 1.0:

- hook_potency (0-1): Does the opening hook match BI's pattern?
  BI hooks are typically a shocking statistic, a dramatic moment, or a counter-intuitive claim.
  Score 1.0 if it opens with a specific number or dramatic scene-setter. 0.5 if generic.

- title_formula_fit (0-1): Does the title match BI title formulas?
  BI uses: "How X became Y", "Why X is Z", "The rise/fall of X", "Inside X", "X explained"
  Score 1.0 for exact formula match, 0.5 for close, 0.0 for generic.

- act_architecture (0-1): Compare act count and pacing to BI average.
  BI avg: {avg_act_count} acts, {avg_act_duration_seconds}s per act.
  Penalise heavily if act count < 4 or > 8, or if any act is >300s.

- data_density (0-1): How many specific stats/numbers appear in key points?
  BI avg: {avg_stat_count} data points per documentary.
  Count numbers/percentages/dollar figures in the storyline key points.

- human_narrative_placement (0-1): Is there a human story, and is it in acts 4-5?
  BI places the human element at act {human_story_act_avg:.0f} on average.
  Score 1.0 if human story is in act 4 or 5, 0.5 if elsewhere, 0.0 if absent.

- tension_release_rhythm (0-1): Does the arc alternate tension and resolution?
  BI pattern: problem (act1) → context (act2) → evidence/tension (act3-4) → human (act5) → resolution (act6)
  Score based on how well the act purposes follow this pattern.

- closing_device (0-1): Does the closing match BI's forward-looking trademark?
  BI closes 70%+ with a forward-looking statement ("what comes next", "what this means for the future")
  Score 1.0 for forward-look, 0.5 for open question, 0.2 for plain summary.

For gaps and strengths, be specific — reference actual BI patterns from the library.
For closest_reference_title, pick the most thematically similar BI doc from the sample titles."""


class BenchmarkAgent:
    """
    Scores a generated storyline against the BI pattern library.

    Loads the pattern library from the local JSON cache on first use.
    Falls back gracefully if no corpus has been built yet.

    Example::

        agent = BenchmarkAgent()
        result = await agent.run(state)
    """

    def __init__(self) -> None:
        self._library: Optional[BIPatternLibrary] = None
        _llm = ChatAnthropic(
            model=settings.claude_haiku_model,
            api_key=settings.anthropic_api_key,
            max_tokens=1500,
            temperature=0.1,
        )
        self._structured_llm = _llm.with_structured_output(BenchmarkScores)

    def _load_library(self) -> Optional[BIPatternLibrary]:
        """Load pattern library from JSON cache (fast path)."""
        if self._library:
            return self._library
        cache_path = Path(settings.bi_pattern_cache_path)
        if not cache_path.exists():
            log.warning("benchmarker.no_corpus", hint="Run: python -m backend.scripts.build_corpus")
            return None
        try:
            self._library = BIPatternLibrary.model_validate_json(cache_path.read_text())
            log.info("benchmarker.library_loaded", doc_count=self._library.doc_count)
            return self._library
        except Exception as exc:
            log.error("benchmarker.library_load_failed", error=str(exc))
            return None

    def _build_prompt(self, storyline: StorylineProposal, library: BIPatternLibrary) -> str:
        acts_text = "\n".join(
            f"  Act {a.act_number} ({a.estimated_duration_seconds}s): {a.act_title}\n"
            f"    Purpose: {a.purpose}\n"
            f"    Key points: {', '.join(a.key_points[:4])}"
            for a in storyline.acts
        )
        sample_hooks = "\n".join(f"  - {h}" for h in library.sample_hooks[:5])
        sample_titles = "\n".join(f"  - {t}" for t in library.sample_titles[:15])

        return (
            f"=== GENERATED STORYLINE ===\n"
            f"Title: {storyline.title}\n"
            f"Logline: {storyline.logline}\n"
            f"Opening Hook: {storyline.opening_hook}\n"
            f"Closing Statement: {storyline.closing_statement}\n"
            f"Total Duration: {storyline.total_estimated_duration_seconds}s "
            f"({storyline.total_estimated_duration_seconds // 60} min)\n\n"
            f"Acts ({len(storyline.acts)} total):\n{acts_text}\n\n"
            f"=== BI PATTERN LIBRARY (from {library.doc_count} docs) ===\n"
            f"Avg act count: {library.avg_act_count:.1f}\n"
            f"Avg act duration: {library.avg_act_duration_seconds:.0f}s\n"
            f"Avg stats per doc: {library.avg_stat_count:.1f}\n"
            f"Human story typically at act: {library.human_story_act_avg:.1f}\n"
            f"Hook type distribution: {json.dumps(library.hook_type_distribution)}\n"
            f"Closing device distribution: {json.dumps(library.closing_device_distribution)}\n"
            f"Title formula distribution: {json.dumps(library.title_formula_distribution)}\n\n"
            f"Sample BI hooks:\n{sample_hooks}\n\n"
            f"BI reference titles:\n{sample_titles}"
        )

    async def run(self, state: dict) -> dict:
        """
        Score the selected storyline against BI patterns.

        Returns:
            Partial state update with ``benchmark_report``.
            If no corpus exists, returns empty benchmark_report with a warning.
        """
        storyline: StorylineProposal = state["selected_storyline"]
        topic: str = state["topic"]

        log.info("benchmarker.start", topic=topic, title=storyline.title)

        library = self._load_library()
        if not library:
            log.warning("benchmarker.skipped", reason="No BI corpus built yet")
            return {"benchmark_report": None}

        system = _SYSTEM_PROMPT.format(
            doc_count=library.doc_count,
            avg_act_count=library.avg_act_count,
            avg_act_duration_seconds=library.avg_act_duration_seconds,
            avg_stat_count=library.avg_stat_count,
            human_story_act_avg=library.human_story_act_avg,
        )

        scores: BenchmarkScores = await self._structured_llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=self._build_prompt(storyline, library)),
        ])

        report = BenchmarkReport.from_scores(scores)

        log.info(
            "benchmarker.complete",
            topic=topic,
            bi_score=f"{report.bi_similarity_score:.2f}",
            grade=report.grade,
        )

        return {"benchmark_report": report}
