"""
Research Session ORM and Pydantic models.

A research session is a chat-style, per-user research workspace that holds a
single consolidated report. Each follow-up prompt re-synthesizes the report
(integrating new findings, honoring removal/extension requests) and the merged
citation list grows accordingly.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.database import Base


class ResearchSessionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ResearchSessionORM(Base):
    """Persisted chat-style research session."""

    __tablename__ = "research_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    turns: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    web_search_requests: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ResearchSessionStatus.COMPLETED.value,
    )
    active_operation: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    pending_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    operation_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    operation_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class ResearchSessionCitation(BaseModel):
    title: str
    url: str
    cited_text: Optional[str] = None


class ResearchSessionTurn(BaseModel):
    prompt: str
    created_at: datetime
    status: ResearchSessionStatus = ResearchSessionStatus.COMPLETED
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    report_markdown: str = ""
    citations: list[ResearchSessionCitation] = Field(default_factory=list)
    web_search_requests: int = 0


class ResearchSessionCreate(BaseModel):
    prompt: str = Field(..., min_length=4, max_length=2000)


class ResearchSessionTurnCreate(BaseModel):
    prompt: str = Field(..., min_length=4, max_length=2000)


class ResearchSessionRead(BaseModel):
    id: uuid.UUID
    title: str
    report_markdown: str
    citations: list[ResearchSessionCitation] = Field(default_factory=list)
    turns: list[ResearchSessionTurn] = Field(default_factory=list)
    model: Optional[str] = None
    web_search_requests: int = 0
    status: ResearchSessionStatus = ResearchSessionStatus.COMPLETED
    active_operation: Optional[str] = None
    pending_prompt: Optional[str] = None
    error_message: Optional[str] = None
    operation_started_at: Optional[datetime] = None
    operation_completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResearchSessionListItem(BaseModel):
    id: uuid.UUID
    title: str
    status: ResearchSessionStatus = ResearchSessionStatus.COMPLETED
    active_operation: Optional[str] = None
    pending_prompt: Optional[str] = None
    error_message: Optional[str] = None
    operation_started_at: Optional[datetime] = None
    updated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
