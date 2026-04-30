"""Add quality gate columns to stories and admin_notifications table

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        # Stories: quality gate tracking columns
        op.execute(
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS pipeline_cycles_run INTEGER NOT NULL DEFAULT 1"
        )
        op.execute(
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS pipeline_failure_summary TEXT"
        )

        # Admin notifications table
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_notifications (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                story_id UUID,
                level VARCHAR(16) NOT NULL DEFAULT 'warning',
                title VARCHAR(512) NOT NULL,
                message TEXT NOT NULL,
                technical_detail TEXT,
                suggested_fix TEXT,
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                read_at TIMESTAMPTZ
            )
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_admin_notifications_is_read ON admin_notifications (is_read)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_admin_notifications_created_at ON admin_notifications (created_at DESC)"
        )
    else:
        for col, col_type, kwargs in [
            ("pipeline_cycles_run", sa.Integer(), {"server_default": "1", "nullable": False}),
            ("pipeline_failure_summary", sa.Text(), {"nullable": True}),
        ]:
            try:
                op.add_column("stories", sa.Column(col, col_type, **kwargs))
            except Exception:
                pass

        try:
            op.create_table(
                "admin_notifications",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("story_id", sa.String(36), nullable=True),
                sa.Column("level", sa.String(16), nullable=False, server_default="warning"),
                sa.Column("title", sa.String(512), nullable=False),
                sa.Column("message", sa.Text(), nullable=False),
                sa.Column("technical_detail", sa.Text(), nullable=True),
                sa.Column("suggested_fix", sa.Text(), nullable=True),
                sa.Column("is_read", sa.Boolean(), nullable=False, server_default="0"),
                sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
                sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            )
        except Exception:
            pass


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP INDEX IF EXISTS ix_admin_notifications_created_at")
        op.execute("DROP INDEX IF EXISTS ix_admin_notifications_is_read")
        op.execute("DROP TABLE IF EXISTS admin_notifications")
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS pipeline_failure_summary")
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS pipeline_cycles_run")
    else:
        try:
            op.drop_table("admin_notifications")
        except Exception:
            pass
        for col in ("pipeline_failure_summary", "pipeline_cycles_run"):
            try:
                op.drop_column("stories", col)
            except Exception:
                pass
