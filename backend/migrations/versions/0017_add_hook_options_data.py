"""Add ideation hook options

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: Union[str, None] = "0016"
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
        op.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS hook_options_data JSONB")
        return

    if not _has_column("stories", "hook_options_data"):
        op.add_column("stories", sa.Column("hook_options_data", _json_type(), nullable=True))


def downgrade() -> None:
    if _is_postgres():
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS hook_options_data")
        return

    if _has_column("stories", "hook_options_data"):
        op.drop_column("stories", "hook_options_data")
