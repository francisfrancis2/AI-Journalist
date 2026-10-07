"""Persisted models and API schemas for the Idea Generator workspace."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Column,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base


class IdeaFormat(str, Enum):
    DOCUMENTARY = "documentary"
    EXPERT_INTERVIEW = "expert_interview"


class IdeaRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CoverageLevel(str, Enum):
    FULL = "full"
    PARTIAL = "partial"


class IdeaState(str, Enum):
    ACTIVE = "active"
    SAVED = "saved"
    DISMISSED = "dismissed"


idea_source_links = Table(
    "idea_source_links",
    Base.metadata,
    Column("idea_id", UUID(as_uuid=True), ForeignKey("generated_ideas.id", ondelete="CASCADE"), primary_key=True),
    Column("source_id", UUID(as_uuid=True), ForeignKey("idea_sources.id", ondelete="CASCADE"), primary_key=True),
)

idea_signal_links = Table(
    "idea_signal_links",
    Base.metadata,
    Column("idea_id", UUID(as_uuid=True), ForeignKey("generated_ideas.id", ondelete="CASCADE"), primary_key=True),
    Column("signal_id", UUID(as_uuid=True), ForeignKey("idea_signals.id", ondelete="CASCADE"), primary_key=True),
)


class IdeaGenerationRunORM(Base):
    __tablename__ = "idea_generation_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_idea_runs_user_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    geography: Mapped[str] = mapped_column(String(8), nullable=False, default="AE")
    trend_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=IdeaRunStatus.QUEUED.value, index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    stage_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_level: Mapped[str] = mapped_column(String(16), nullable=False, default=CoverageLevel.PARTIAL.value)
    coverage_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    provider_statuses: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    candidate_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    usage_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v2")
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="idea-generator-v2")
    previous_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    ideas: Mapped[list["GeneratedIdeaORM"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin", order_by="GeneratedIdeaORM.rank"
    )
    sources: Mapped[list["IdeaSourceORM"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )
    signals: Mapped[list["IdeaSignalORM"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )


class GeneratedIdeaORM(Base):
    __tablename__ = "generated_ideas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idea_generation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    sector: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    premise: Mapped[str] = mapped_column(Text, nullable=False)
    why_now: Mapped[str] = mapped_column(Text, nullable=False)
    uae_relevance: Mapped[str] = mapped_column(Text, nullable=False)
    central_tension: Mapped[str] = mapped_column(Text, nullable=False)
    target_audience: Mapped[str] = mapped_column(String(300), nullable=False)
    business_significance: Mapped[str] = mapped_column(Text, nullable=False)
    format_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    score_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    strength: Mapped[str] = mapped_column(String(24), nullable=False)
    coverage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    verification_gaps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default=IdeaState.ACTIVE.value)
    story_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    research_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    run: Mapped[IdeaGenerationRunORM] = relationship(back_populates="ideas")
    sources: Mapped[list["IdeaSourceORM"]] = relationship(
        secondary=idea_source_links, lazy="selectin", order_by="IdeaSourceORM.published_at.desc()"
    )
    signals: Mapped[list["IdeaSignalORM"]] = relationship(
        secondary=idea_signal_links, lazy="selectin"
    )


class IdeaSourceORM(Base):
    __tablename__ = "idea_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idea_generation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    credibility: Mapped[str] = mapped_column(String(24), nullable=False, default="medium")
    is_uae_relevant: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_primary: Mapped[bool] = mapped_column(nullable=False, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run: Mapped[IdeaGenerationRunORM] = relationship(back_populates="sources")


class IdeaSignalORM(Base):
    __tablename__ = "idea_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("idea_generation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    geography: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    geography_meaning: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    window_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metric: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reliability: Mapped[str] = mapped_column(String(24), nullable=False, default="medium")
    is_cached: Mapped[bool] = mapped_column(nullable=False, default=False)
    raw_reference: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run: Mapped[IdeaGenerationRunORM] = relationship(back_populates="signals")


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdeaGenerationCreate(StrictSchema):
    format: IdeaFormat
    previous_run_id: Optional[uuid.UUID] = None


class IdeaStateUpdate(StrictSchema):
    state: IdeaState


class ProviderStatusRead(StrictSchema):
    status: Literal["complete", "partial", "unavailable", "not_configured", "failed"]
    detail: str
    evidence_count: int = 0


class IdeaSourceRead(StrictSchema):
    id: uuid.UUID
    title: str
    url: Optional[str] = None
    domain: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[datetime] = None
    excerpt: str
    source_type: str
    credibility: str
    is_uae_relevant: bool
    is_primary: bool


class IdeaSignalRead(StrictSchema):
    id: uuid.UUID
    provider: str
    signal_type: str
    topic: str
    query: Optional[str] = None
    geography: Optional[str] = None
    geography_meaning: Optional[str] = None
    metric: Optional[str] = None
    values: dict[str, Any] = Field(default_factory=dict)
    reliability: str


class GeneratedIdeaRead(StrictSchema):
    id: uuid.UUID
    rank: int
    format: IdeaFormat
    sector: str
    title: str
    premise: str
    why_now: str
    uae_relevance: str
    central_tension: str
    target_audience: str
    business_significance: str
    format_details: dict[str, Any]
    score_breakdown: dict[str, float]
    score: float
    strength: str
    coverage: dict[str, Any]
    verification_gaps: list[str]
    state: IdeaState
    story_id: Optional[uuid.UUID] = None
    research_session_id: Optional[uuid.UUID] = None
    sources: list[IdeaSourceRead] = Field(default_factory=list)
    signals: list[IdeaSignalRead] = Field(default_factory=list)


class IdeaGenerationRunRead(StrictSchema):
    id: uuid.UUID
    format: IdeaFormat
    geography: str
    trend_window_days: int
    status: IdeaRunStatus
    stage: str
    stage_progress: int
    coverage_level: CoverageLevel
    coverage_reasons: list[str]
    provider_statuses: dict[str, ProviderStatusRead]
    candidate_metrics: dict[str, Any]
    usage_metrics: dict[str, Any]
    previous_run_id: Optional[uuid.UUID] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    ideas: list[GeneratedIdeaRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class IdeaGenerationRunListItem(StrictSchema):
    id: uuid.UUID
    format: IdeaFormat
    status: IdeaRunStatus
    coverage_level: CoverageLevel
    stage: str
    idea_count: int
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None


class IdeaHandoffPreview(StrictSchema):
    idea_id: uuid.UUID
    target: Literal["story", "research"]
    allowed: bool
    prompt: str
    title: str
    inherited_source_count: int
    message: str

