"""
ORM and Pydantic models for Story, Storyline, and Script entities.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.database import Base


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

    # Research artefacts (JSON blobs)
    research_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    analysis_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    storyline_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    evaluation_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    script_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Quality metrics
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_duration_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # S3 reference for the final script document
    script_s3_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # BI benchmark scores
    benchmark_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

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
    target_duration_minutes: int = Field(12, ge=10, le=15)

    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Topic cannot be blank")
        return v.strip()


class StoryRead(BaseModel):
    """Full story response schema."""
    id: uuid.UUID
    title: str
    topic: str
    status: StoryStatus
    tone: StoryTone
    quality_score: Optional[float]
    word_count: Optional[int]
    estimated_duration_minutes: Optional[float]
    script_s3_key: Optional[str]
    error_message: Optional[str]
    iteration_count: int
    evaluation_data: Optional[dict] = None
    benchmark_data: Optional[dict] = None
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
    quality_score: Optional[float]
    estimated_duration_minutes: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class ScriptSection(BaseModel):
    """A single section (act/segment) within the final script."""
    section_number: int
    title: str
    narration: str
    estimated_seconds: int = 60


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
