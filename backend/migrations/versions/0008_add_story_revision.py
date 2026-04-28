"""Add parent_story_id and revision columns to stories

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        op.execute(
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS parent_story_id UUID DEFAULT NULL"
        )
        op.execute(
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1"
        )
    else:
        try:
            op.add_column("stories", sa.Column("parent_story_id", sa.String(36), nullable=True))
        except Exception:
            pass
        try:
            op.add_column("stories", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        except Exception:
            pass


def downgrade() -> None:
    if _is_postgres():
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS parent_story_id")
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS revision")
    else:
        op.drop_column("stories", "parent_story_id")
        op.drop_column("stories", "revision")
