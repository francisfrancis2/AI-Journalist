"""Add library_key to benchmark corpus tables to support multi-channel libraries

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add library_key to reference docs — default "bi" for all existing rows
    op.add_column(
        "bi_reference_docs",
        sa.Column("library_key", sa.String(32), nullable=False, server_default="bi"),
    )
    op.create_index("ix_bi_reference_docs_library_key", "bi_reference_docs", ["library_key"])

    # Add library_key to pattern library — default "bi" for all existing rows
    op.add_column(
        "bi_pattern_library",
        sa.Column("library_key", sa.String(32), nullable=False, server_default="bi"),
    )
    op.create_index("ix_bi_pattern_library_library_key", "bi_pattern_library", ["library_key"])


def downgrade() -> None:
    op.drop_index("ix_bi_pattern_library_library_key", table_name="bi_pattern_library")
    op.drop_column("bi_pattern_library", "library_key")
    op.drop_index("ix_bi_reference_docs_library_key", table_name="bi_reference_docs")
    op.drop_column("bi_reference_docs", "library_key")
