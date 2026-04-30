"""AdminNotification ORM and Pydantic schemas."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.database import Base


class AdminNotificationORM(Base):
    """Persisted admin notification created when pipeline quality failures occur."""

    __tablename__ = "admin_notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    technical_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_fix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminNotificationRead(BaseModel):
    id: uuid.UUID
    story_id: Optional[uuid.UUID] = None
    level: str
    title: str
    message: str
    technical_detail: Optional[str] = None
    suggested_fix: Optional[str] = None
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
