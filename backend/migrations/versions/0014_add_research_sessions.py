"""Add research_sessions table

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS research_sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title VARCHAR(200) NOT NULL,
                report_markdown TEXT NOT NULL DEFAULT '',
                citations JSONB NOT NULL DEFAULT '[]'::jsonb,
                turns JSONB NOT NULL DEFAULT '[]'::jsonb,
                model VARCHAR(128),
                web_search_requests INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            )
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_research_sessions_user_id "
            "ON research_sessions (user_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_research_sessions_user_updated "
            "ON research_sessions (user_id, updated_at DESC)"
        )
    else:
        op.create_table(
            "research_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("report_markdown", sa.Text, nullable=False, server_default=""),
            sa.Column("citations", sa.JSON, nullable=False),
            sa.Column("turns", sa.JSON, nullable=False),
            sa.Column("model", sa.String(128), nullable=True),
            sa.Column(
                "web_search_requests",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_research_sessions_user_id",
            "research_sessions",
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP INDEX IF EXISTS ix_research_sessions_user_updated")
        op.execute("DROP INDEX IF EXISTS ix_research_sessions_user_id")
        op.execute("DROP TABLE IF EXISTS research_sessions")
    else:
        op.drop_index("ix_research_sessions_user_id", table_name="research_sessions")
        op.drop_table("research_sessions")
