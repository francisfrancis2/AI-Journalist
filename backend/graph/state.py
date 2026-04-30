"""
LangGraph state definition for the AI Journalist pipeline.

The JournalistState TypedDict is the single shared object that every node
reads from and writes back to as the graph executes.
"""

import uuid
from typing import Annotated, Any, Optional

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from typing_extensions import TypedDict

from backend.models.benchmark import BenchmarkReport
from backend.models.research import (
    AnalysisResult,
    EvaluationReport,
    ResearchPackage,
    StorylineProposal,
)
from backend.models.story import FinalScript, ImprovementPlan, ScriptAuditReport, StoryTone


class JournalistState(TypedDict):
    """
    Shared state flowing through every node in the LangGraph journalist pipeline.

    Field naming convention:
    - *_data  : structured Pydantic artefacts
    - *_raw   : unstructured text returned by an LLM node
    - messages: conversation history (accumulated via add_messages reducer)
    - flags   : booleans that control routing decisions
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    story_id: str                           # UUID string of the DB story record
    topic: str                              # Original topic provided by the user
    tone: StoryTone                         # Target documentary tone
    target_duration_minutes: int             # Requested script duration
    target_audience: Optional[str]           # Optional audience / platform target

    # ── Conversation history (LangGraph built-in reducer) ─────────────────────
    messages: Annotated[list[BaseMessage], add_messages]

    # ── Research phase ────────────────────────────────────────────────────────
    research_package: Optional[ResearchPackage]
    research_iteration: int                 # How many times the researcher has run

    # ── Analysis phase ────────────────────────────────────────────────────────
    analysis_result: Optional[AnalysisResult]

    # ── Storyline phase ───────────────────────────────────────────────────────
    storyline_proposals: list[StorylineProposal]  # Multiple candidates
    selected_storyline: Optional[StorylineProposal]
    user_rewrite_recommendations: list[str]   # User-selected improvement goals for a guided revision

    # ── Evaluation phase ──────────────────────────────────────────────────────
    evaluation_report: Optional[EvaluationReport]
    benchmark_report: Optional[BenchmarkReport]  # Benchmark scores (runs parallel to evaluator)
    refinement_cycle: int                   # How many times evaluation→refinement has run

    # ── Script phase ──────────────────────────────────────────────────────────
    final_script: Optional[FinalScript]
    script_audit_report: Optional[ScriptAuditReport]
    script_s3_key: Optional[str]            # S3 key of the uploaded script document
    script_revision_cycle: int              # How many audit-triggered rewrites have run

    # ── Quality gate ──────────────────────────────────────────────────────────
    pipeline_cycle: int                     # Full research→script cycles completed
    best_script: Optional[FinalScript]      # Best script seen across all cycles
    best_script_score: float                # Score of best_script
    quality_improvement_plan: Optional[ImprovementPlan]  # Guidance for next cycle
    pipeline_failure_summary: Optional[str] # Human-readable failure reason (shown to user)
    is_technical_failure: bool              # True → also create admin notification
    _quality_gate_route: Optional[str]      # Transient: "restart" | "done" (set by quality gate)

    # ── Control flow flags ────────────────────────────────────────────────────
    needs_more_research: bool
    approved_for_scripting: bool
    pipeline_complete: bool

    # ── Error handling ────────────────────────────────────────────────────────
    error: Optional[str]
    failed_node: Optional[str]


def create_initial_state(
    topic: str,
    story_id: Optional[str] = None,
    tone: StoryTone = StoryTone.EXPLANATORY,
    target_duration_minutes: int = 12,
    target_audience: Optional[str] = None,
) -> JournalistState:
    """
    Factory that returns a correctly-initialised JournalistState.

    Args:
        topic: The research topic / question for the story.
        story_id: Optional existing DB story UUID; generates a new one if omitted.
        tone: Documentary tone to target.

    Returns:
        A fully populated JournalistState with sensible defaults.
    """
    return JournalistState(
        story_id=story_id or str(uuid.uuid4()),
        topic=topic,
        tone=tone,
        target_duration_minutes=target_duration_minutes,
        target_audience=target_audience,
        messages=[],
        research_package=None,
        research_iteration=0,
        analysis_result=None,
        storyline_proposals=[],
        selected_storyline=None,
        user_rewrite_recommendations=[],
        evaluation_report=None,
        benchmark_report=None,
        refinement_cycle=0,
        final_script=None,
        script_audit_report=None,
        script_s3_key=None,
        script_revision_cycle=0,
        pipeline_cycle=0,
        best_script=None,
        best_script_score=0.0,
        quality_improvement_plan=None,
        pipeline_failure_summary=None,
        is_technical_failure=False,
        _quality_gate_route=None,
        needs_more_research=False,
        approved_for_scripting=False,
        pipeline_complete=False,
        error=None,
        failed_node=None,
    )
