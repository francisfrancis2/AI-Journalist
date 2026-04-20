"""
Benchmark models — reference corpus ORM and Pydantic schemas.
"""

import uuid
from datetime import datetime, timezone
import re
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON

from backend.db.database import Base


_SOURCE_NAME_RE = re.compile(
    r"\b(Business Insider|CNBC Make It|CNBC Making It|Vox|Johnny Harris|BI)\b",
    re.IGNORECASE,
)


def _neutralize_benchmark_source_names(value: str) -> str:
    """Keep benchmark output source-neutral for user-facing results."""
    return _SOURCE_NAME_RE.sub("benchmark corpus", value)


# ── ORM Models ────────────────────────────────────────────────────────────────

class BIReferenceDocORM(Base):
    """One YouTube documentary used as a benchmark reference (any supported channel)."""
    __tablename__ = "bi_reference_docs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    library_key: Mapped[str] = mapped_column(String(32), nullable=False, default="bi", index=True)
    youtube_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_structure: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class BIPatternLibraryORM(Base):
    """Synthesised pattern library for any supported benchmark channel."""
    __tablename__ = "bi_pattern_library"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    library_key: Mapped[str] = mapped_column(String(32), nullable=False, default="bi", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False)
    patterns: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class DocStructure(BaseModel):
    """Structural features extracted from a single benchmark documentary transcript."""
    hook_type: str                      # "stat" | "question" | "scene" | "claim"
    hook_text: str                      # first 2-3 sentences verbatim
    act_count: int
    act_titles: list[str]
    act_durations_seconds: list[int]
    has_human_story: bool
    human_story_act: Optional[int]      # which act number (1-indexed)
    closing_device: str                 # "forward_look" | "open_question" | "summary" | "call_to_action"
    stat_count: int                     # number of specific statistics in doc
    rhetorical_question_count: int
    title_formula: str                  # "how_x_became_y" | "why_x_is_z" | "the_rise_of" | "other"


class BIPatternLibrary(BaseModel):
    """Synthesised patterns across a benchmark corpus — used by BenchmarkAgent."""
    version: int
    doc_count: int
    avg_act_count: float
    avg_act_duration_seconds: float
    hook_type_distribution: dict[str, float]       # e.g. {"stat": 0.45, "question": 0.30}
    title_formula_distribution: dict[str, float]
    closing_device_distribution: dict[str, float]
    avg_stat_count: float
    avg_rhetorical_questions: float
    human_story_act_avg: float                     # typically 4-5
    sample_hooks: list[str]                        # 5 strongest opening hooks from corpus
    sample_titles: list[str]                       # all reference titles


class BenchmarkCriterionDetail(BaseModel):
    """Per-criterion benchmark explanation for user-facing results."""

    criterion: str
    label: str
    score: float = Field(ge=0.0, le=1.0)
    assessment: str
    improvement: str = ""


class BenchmarkScores(BaseModel):
    """Structured output from the BenchmarkAgent LLM call."""
    hook_potency: float = Field(ge=0.0, le=1.0, description="How strongly the hook creates immediate stakes")
    title_formula_fit: float = Field(ge=0.0, le=1.0, description="How well the title fits proven documentary title patterns")
    act_architecture: float = Field(ge=0.0, le=1.0, description="Act count, duration, and arc shape vs benchmark averages")
    data_density: float = Field(ge=0.0, le=1.0, description="Specific stats per act vs benchmark averages")
    human_narrative_placement: float = Field(ge=0.0, le=1.0, description="Human story placement vs benchmark patterns")
    tension_release_rhythm: float = Field(ge=0.0, le=1.0, description="Alternating tension-release pattern across acts")
    closing_device: float = Field(ge=0.0, le=1.0, description="How well the closing resolves and points forward")
    closest_reference_title: Optional[str] = Field(None, description="Deprecated; do not use in user-facing results")
    gaps: list[str] = Field(default_factory=list, description="Specific gaps vs benchmark standard")
    strengths: list[str] = Field(default_factory=list, description="Elements that match or exceed benchmark standard")
    criterion_details: list[BenchmarkCriterionDetail] = Field(default_factory=list)


class BenchmarkReport(BaseModel):
    """Full benchmark report stored on the story record."""
    bi_similarity_score: float          # weighted average of all criteria
    hook_potency: float
    title_formula_fit: float
    act_architecture: float
    data_density: float
    human_narrative_placement: float
    tension_release_rhythm: float
    closing_device: float
    closest_reference_title: Optional[str] = None
    gaps: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    criterion_details: list[BenchmarkCriterionDetail] = Field(default_factory=list)
    grade: str = "C"                    # A (≥0.85) | B (≥0.70) | C (≥0.55) | D (<0.55)
    library_key: str = "combined"
    library_label: str = "Benchmark Corpus"
    library_version: Optional[int] = None
    reference_doc_count: int = 0
    built_at: Optional[datetime] = None
    stale: bool = False
    status_notes: list[str] = Field(default_factory=list)

    @classmethod
    def from_scores(cls, scores: BenchmarkScores) -> "BenchmarkReport":
        weights = {
            "hook_potency": 0.20,
            "title_formula_fit": 0.10,
            "act_architecture": 0.20,
            "data_density": 0.15,
            "human_narrative_placement": 0.15,
            "tension_release_rhythm": 0.10,
            "closing_device": 0.10,
        }
        overall = sum(
            getattr(scores, field) * w for field, w in weights.items()
        )
        grade = "A" if overall >= 0.85 else "B" if overall >= 0.70 else "C" if overall >= 0.55 else "D"
        labels = {
            "hook_potency": "Hook Potency",
            "title_formula_fit": "Title Formula Fit",
            "act_architecture": "Act Architecture",
            "data_density": "Data Density",
            "human_narrative_placement": "Human Narrative",
            "tension_release_rhythm": "Tension / Release",
            "closing_device": "Closing Device",
        }
        details_by_key = {detail.criterion: detail for detail in scores.criterion_details}
        criterion_details = []
        for field, label in labels.items():
            score = getattr(scores, field)
            detail = details_by_key.get(field)
            criterion_details.append(
                BenchmarkCriterionDetail(
                    criterion=field,
                    label=_neutralize_benchmark_source_names(
                        detail.label if detail and detail.label else label
                    ),
                    score=score,
                    assessment=_neutralize_benchmark_source_names(
                        detail.assessment if detail else f"{label} scored {score:.2f}."
                    ),
                    improvement=_neutralize_benchmark_source_names(
                        detail.improvement if detail else ""
                    ),
                )
            )

        return cls(
            bi_similarity_score=round(overall, 3),
            hook_potency=scores.hook_potency,
            title_formula_fit=scores.title_formula_fit,
            act_architecture=scores.act_architecture,
            data_density=scores.data_density,
            human_narrative_placement=scores.human_narrative_placement,
            tension_release_rhythm=scores.tension_release_rhythm,
            closing_device=scores.closing_device,
            closest_reference_title=None,
            gaps=[_neutralize_benchmark_source_names(gap) for gap in scores.gaps],
            strengths=[
                _neutralize_benchmark_source_names(strength)
                for strength in scores.strengths
            ],
            criterion_details=criterion_details,
            grade=grade,
        )
