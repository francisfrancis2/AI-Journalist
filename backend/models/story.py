"""
ORM and Pydantic models for Story, Storyline, and Script entities.
"""

import uuid
from datetime import datetime
from enum import Enum
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.api.security import validate_topic
from backend.config import settings
from backend.db.database import Base


_BENCHMARK_SOURCE_RE = re.compile(
    r"\b(Business Insider|CNBC Make It|CNBC Making It|Vox|Johnny Harris|BI)\b",
    re.IGNORECASE,
)


def _neutralize_benchmark_source_names(value: str) -> str:
    return _BENCHMARK_SOURCE_RE.sub("benchmark corpus", value)


def _neutralize_many(values: list[str]) -> list[str]:
    return [_neutralize_benchmark_source_names(value) for value in values]


# ── Enumerations ──────────────────────────────────────────────────────────────

class StoryStatus(str, Enum):
    PENDING = "pending"
    RESEARCHING = "researching"
    ANALYSING = "analysing"
    WRITING_STORYLINE = "writing_storyline"
    EVALUATING = "evaluating"
    SCRIPTING = "scripting"
    COMPLETED = "completed"
    FAILED = "failed"


class StoryTone(str, Enum):
    INVESTIGATIVE = "investigative"
    EXPLANATORY = "explanatory"
    NARRATIVE = "narrative"
    PROFILE = "profile"
    TREND = "trend"


# ── ORM Models ────────────────────────────────────────────────────────────────

class StoryORM(Base):
    """Persisted story record tracked through the entire pipeline."""

    __tablename__ = "stories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default=StoryStatus.PENDING)
    tone: Mapped[str] = mapped_column(String(64), default=StoryTone.EXPLANATORY)
    target_duration_minutes: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    target_audience: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Research artefacts (JSON blobs)
    research_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    analysis_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    storyline_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    evaluation_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    script_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    script_audit_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Quality metrics
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_duration_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # S3 reference for the final script document
    script_s3_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Benchmark scores
    benchmark_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Previous script versions (list of {version, script, created_at})
    script_versions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, default=list)

    # Revision lineage — set when this story was created as a revision of another
    parent_story_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    iteration_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class StoryCreate(BaseModel):
    """Request body for creating a new story."""
    topic: str = Field(..., min_length=10, max_length=1000, description="Research topic or question")
    title: Optional[str] = Field(None, max_length=512, description="Optional working title")
    tone: StoryTone = StoryTone.EXPLANATORY
    target_duration_minutes: int = Field(10, ge=5, le=15)
    target_audience: Optional[str] = Field(
        None,
        max_length=256,
        description="Optional audience or platform target for the script",
    )

    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Topic cannot be blank")
        v = v.strip()
        return validate_topic(v)


class StoryRead(BaseModel):
    """Full story response schema."""
    id: uuid.UUID
    title: str
    topic: str
    status: StoryStatus
    tone: StoryTone
    target_duration_minutes: int
    target_audience: Optional[str]
    quality_score: Optional[float]
    word_count: Optional[int]
    estimated_duration_minutes: Optional[float]
    script_s3_key: Optional[str]
    error_message: Optional[str]
    iteration_count: int
    evaluation_data: Optional[dict] = None
    benchmark_data: Optional[dict] = None
    script_audit_data: Optional[dict] = None
    script_versions: Optional[list] = None
    parent_story_id: Optional[uuid.UUID] = None
    revision: int = 1
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StoryListItem(BaseModel):
    """Lightweight summary for list views."""
    id: uuid.UUID
    title: str
    topic: str
    status: StoryStatus
    tone: StoryTone
    target_duration_minutes: int
    target_audience: Optional[str]
    quality_score: Optional[float]
    estimated_duration_minutes: Optional[float]
    benchmark_data: Optional[dict] = None
    parent_story_id: Optional[uuid.UUID] = None
    revision: int = 1
    created_at: datetime

    model_config = {"from_attributes": True}


class ScriptSection(BaseModel):
    """A single section (act/segment) within the final script."""
    section_number: int
    title: str
    narration: str
    estimated_seconds: int = 60
    source_ids: list[str] = Field(default_factory=list)


class FinalScript(BaseModel):
    """The complete, production-ready script for a story."""
    story_id: uuid.UUID
    title: str
    logline: str
    opening_hook: str
    sections: list[ScriptSection]
    closing_statement: str
    total_word_count: int
    estimated_duration_minutes: float
    sources: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScriptAuditCriteria(BaseModel):
    """Scores (0-1) for the quality of the finished script itself."""

    hook_strength: float = Field(0.0, ge=0.0, le=1.0)
    narrative_flow: float = Field(0.0, ge=0.0, le=1.0)
    evidence_and_specificity: float = Field(0.0, ge=0.0, le=1.0)
    pacing: float = Field(0.0, ge=0.0, le=1.0)
    writing_quality: float = Field(0.0, ge=0.0, le=1.0)
    production_readiness: float = Field(0.0, ge=0.0, le=1.0)

    @property
    def overall_score(self) -> float:
        weights = {
            "hook_strength": 0.20,
            "narrative_flow": 0.20,
            "evidence_and_specificity": 0.20,
            "pacing": 0.15,
            "writing_quality": 0.15,
            "production_readiness": 0.10,
        }
        return sum(getattr(self, field) * weight for field, weight in weights.items())


class ScriptSectionAudit(BaseModel):
    """Section-by-section audit output for the final script."""

    section_number: int
    title: str
    score: float = Field(0.0, ge=0.0, le=1.0)
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    benchmark_notes: list[str] = Field(default_factory=list)
    rewrite_recommendation: str = ""

    @model_validator(mode="after")
    def neutralize_benchmark_sources(self) -> "ScriptSectionAudit":
        self.summary = _neutralize_benchmark_source_names(self.summary)
        self.strengths = _neutralize_many(self.strengths)
        self.weaknesses = _neutralize_many(self.weaknesses)
        self.benchmark_notes = _neutralize_many(self.benchmark_notes)
        self.rewrite_recommendation = _neutralize_benchmark_source_names(self.rewrite_recommendation)
        return self


class BenchmarkComparison(BaseModel):
    """Best-in-class comparison summary against the benchmark corpus."""

    closest_reference_title: Optional[str] = None
    alignment_summary: str = ""
    hook_comparison: str = ""
    structure_comparison: str = ""
    data_density_comparison: str = ""
    closing_comparison: str = ""
    best_in_class_takeaways: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def neutralize_benchmark_sources(self) -> "BenchmarkComparison":
        self.closest_reference_title = None
        self.alignment_summary = _neutralize_benchmark_source_names(self.alignment_summary)
        self.hook_comparison = _neutralize_benchmark_source_names(self.hook_comparison)
        self.structure_comparison = _neutralize_benchmark_source_names(self.structure_comparison)
        self.data_density_comparison = _neutralize_benchmark_source_names(self.data_density_comparison)
        self.closing_comparison = _neutralize_benchmark_source_names(self.closing_comparison)
        self.best_in_class_takeaways = _neutralize_many(self.best_in_class_takeaways)
        return self


class ScriptAuditReport(BaseModel):
    """Full post-script audit report with rewrite guidance."""

    criteria: ScriptAuditCriteria
    overall_score: float = 0.0
    grade: str = "C"
    ready_for_production: bool = False
    audit_summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    rewrite_priorities: list[str] = Field(default_factory=list)
    section_audits: list[ScriptSectionAudit] = Field(default_factory=list)
    benchmark_comparison: Optional[BenchmarkComparison] = None

    @model_validator(mode="after")
    def neutralize_benchmark_sources(self) -> "ScriptAuditReport":
        self.audit_summary = _neutralize_benchmark_source_names(self.audit_summary)
        self.strengths = _neutralize_many(self.strengths)
        self.weaknesses = _neutralize_many(self.weaknesses)
        self.rewrite_priorities = _neutralize_many(self.rewrite_priorities)
        return self

    def compute_overall(self) -> None:
        self.overall_score = self.criteria.overall_score
        self.ready_for_production = self.overall_score >= settings.script_audit_score_threshold
        self.grade = (
            "A" if self.overall_score >= 0.85
            else "B" if self.overall_score >= 0.70
            else "C" if self.overall_score >= 0.55
            else "D"
        )
