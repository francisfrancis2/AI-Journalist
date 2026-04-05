"""Initial stories table

Revision ID: 0001
Revises:
Create Date: 2026-04-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("status", sa.String(64), nullable=False, server_default="pending"),
        sa.Column("tone", sa.String(64), nullable=False, server_default="explanatory"),
        sa.Column("research_data", sa.JSON, nullable=True),
        sa.Column("analysis_data", sa.JSON, nullable=True),
        sa.Column("storyline_data", sa.JSON, nullable=True),
        sa.Column("evaluation_data", sa.JSON, nullable=True),
        sa.Column("script_data", sa.JSON, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("word_count", sa.Integer, nullable=True),
        sa.Column("estimated_duration_minutes", sa.Float, nullable=True),
        sa.Column("script_s3_key", sa.String(1024), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("iteration_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_stories_status", "stories", ["status"])
    op.create_index("ix_stories_created_at", "stories", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_stories_created_at", table_name="stories")
    op.drop_index("ix_stories_status", table_name="stories")
    op.drop_table("stories")
