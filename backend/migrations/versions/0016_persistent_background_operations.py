"""Add persistent operation state for user-launched work

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type() -> sa.types.TypeEngine:
    if _is_postgres():
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return column_name in {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    if _is_postgres():
        op.execute("ALTER TABLE research_sessions ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'completed'")
        op.execute("ALTER TABLE research_sessions ADD COLUMN IF NOT EXISTS active_operation VARCHAR(32)")
        op.execute("ALTER TABLE research_sessions ADD COLUMN IF NOT EXISTS pending_prompt TEXT")
        op.execute("ALTER TABLE research_sessions ADD COLUMN IF NOT EXISTS error_message TEXT")
        op.execute("ALTER TABLE research_sessions ADD COLUMN IF NOT EXISTS operation_started_at TIMESTAMP WITH TIME ZONE")
        op.execute("ALTER TABLE research_sessions ADD COLUMN IF NOT EXISTS operation_completed_at TIMESTAMP WITH TIME ZONE")
        op.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS ideation_operation_data JSONB")
        return

    if not _has_column("research_sessions", "status"):
        op.add_column(
            "research_sessions",
            sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        )
    if not _has_column("research_sessions", "active_operation"):
        op.add_column("research_sessions", sa.Column("active_operation", sa.String(32), nullable=True))
    if not _has_column("research_sessions", "pending_prompt"):
        op.add_column("research_sessions", sa.Column("pending_prompt", sa.Text(), nullable=True))
    if not _has_column("research_sessions", "error_message"):
        op.add_column("research_sessions", sa.Column("error_message", sa.Text(), nullable=True))
    if not _has_column("research_sessions", "operation_started_at"):
        op.add_column("research_sessions", sa.Column("operation_started_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column("research_sessions", "operation_completed_at"):
        op.add_column("research_sessions", sa.Column("operation_completed_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column("stories", "ideation_operation_data"):
        op.add_column("stories", sa.Column("ideation_operation_data", _json_type(), nullable=True))


def downgrade() -> None:
    if _is_postgres():
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS ideation_operation_data")
        op.execute("ALTER TABLE research_sessions DROP COLUMN IF EXISTS operation_completed_at")
        op.execute("ALTER TABLE research_sessions DROP COLUMN IF EXISTS operation_started_at")
        op.execute("ALTER TABLE research_sessions DROP COLUMN IF EXISTS error_message")
        op.execute("ALTER TABLE research_sessions DROP COLUMN IF EXISTS pending_prompt")
        op.execute("ALTER TABLE research_sessions DROP COLUMN IF EXISTS active_operation")
        op.execute("ALTER TABLE research_sessions DROP COLUMN IF EXISTS status")
        return

    for table_name, column_name in (
        ("stories", "ideation_operation_data"),
        ("research_sessions", "operation_completed_at"),
        ("research_sessions", "operation_started_at"),
        ("research_sessions", "error_message"),
        ("research_sessions", "pending_prompt"),
        ("research_sessions", "active_operation"),
        ("research_sessions", "status"),
    ):
        if _has_column(table_name, column_name):
            op.drop_column(table_name, column_name)
