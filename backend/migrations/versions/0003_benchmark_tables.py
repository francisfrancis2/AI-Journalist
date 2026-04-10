"""Add benchmark tables and benchmark_data column to stories

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── bi_reference_docs ─────────────────────────────────────────────────────
    op.create_table(
        "bi_reference_docs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("youtube_id", sa.String(20), nullable=False, unique=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("view_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("like_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("transcript", sa.Text, nullable=True),
        sa.Column("extracted_structure", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_bi_reference_docs_youtube_id", "bi_reference_docs", ["youtube_id"])

    # ── bi_pattern_library ────────────────────────────────────────────────────
    op.create_table(
        "bi_pattern_library",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("doc_count", sa.Integer, nullable=False),
        sa.Column("patterns", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_bi_pattern_library_version", "bi_pattern_library", ["version"])

    # ── benchmark_data column on stories ──────────────────────────────────────
    op.add_column("stories", sa.Column("benchmark_data", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("stories", "benchmark_data")
    op.drop_index("ix_bi_pattern_library_version", table_name="bi_pattern_library")
    op.drop_table("bi_pattern_library")
    op.drop_index("ix_bi_reference_docs_youtube_id", table_name="bi_reference_docs")
    op.drop_table("bi_reference_docs")
