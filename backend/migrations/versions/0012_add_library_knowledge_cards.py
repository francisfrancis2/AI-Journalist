"""Add library knowledge cards

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "library_knowledge_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("library_key", sa.String(32), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("topic_tags", sa.JSON(), nullable=False),
        sa.Column("guidance", sa.JSON(), nullable=False),
        sa.Column("source_doc_id", sa.String(64), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_library_knowledge_cards_library_key", "library_knowledge_cards", ["library_key"])
    op.create_index("ix_library_knowledge_cards_role", "library_knowledge_cards", ["role"])
    op.create_index("ix_library_knowledge_cards_artifact_type", "library_knowledge_cards", ["artifact_type"])


def downgrade() -> None:
    op.drop_index("ix_library_knowledge_cards_artifact_type", table_name="library_knowledge_cards")
    op.drop_index("ix_library_knowledge_cards_role", table_name="library_knowledge_cards")
    op.drop_index("ix_library_knowledge_cards_library_key", table_name="library_knowledge_cards")
    op.drop_table("library_knowledge_cards")
