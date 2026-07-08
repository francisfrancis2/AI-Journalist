"""Add story attachment sources

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: Union[str, None] = "0017"
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
        op.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS attachment_data JSONB")
        return

    if not _has_column("stories", "attachment_data"):
        op.add_column("stories", sa.Column("attachment_data", _json_type(), nullable=True))


def downgrade() -> None:
    if _is_postgres():
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS attachment_data")
        return

    if _has_column("stories", "attachment_data"):
        op.drop_column("stories", "attachment_data")
