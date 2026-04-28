"""Add script_versions column to stories

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        op.execute(
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS script_versions JSONB DEFAULT '[]'::jsonb"
        )
    else:
        try:
            op.add_column("stories", sa.Column("script_versions", sa.JSON(), nullable=True))
        except Exception:
            pass


def downgrade() -> None:
    if _is_postgres():
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS script_versions")
    else:
        op.drop_column("stories", "script_versions")
