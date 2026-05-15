"""Helpers for pruning persistent admin notifications."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.notification import AdminNotificationORM

log = structlog.get_logger(__name__)


async def cleanup_admin_notifications(
    db: AsyncSession,
    *,
    retention_days: int | None = None,
) -> int:
    """
    Delete read admin notifications older than the retention window.

    Runtime stdout logs are platform-managed, but these DB-backed notifications
    should not accumulate forever.
    """
    retention = (
        settings.admin_notification_retention_days
        if retention_days is None
        else retention_days
    )
    if retention <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
    result = await db.execute(
        delete(AdminNotificationORM).where(
            AdminNotificationORM.is_read == True,  # noqa: E712
            AdminNotificationORM.read_at.is_not(None),
            AdminNotificationORM.read_at < cutoff,
        )
    )
    deleted = int(result.rowcount or 0)
    await db.commit()

    if deleted:
        log.info(
            "admin_notifications.cleaned",
            deleted=deleted,
            retention_days=retention,
        )

    return deleted
