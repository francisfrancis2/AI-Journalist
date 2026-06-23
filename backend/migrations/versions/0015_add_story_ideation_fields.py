"""Add story ideation fields

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_type() -> sa.types.TypeEngine:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return column_name in {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    if _is_postgres():
        op.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS ideation_stage VARCHAR(64)")
        op.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS ideation_chat_data JSONB")
        op.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS ideation_research_data JSONB")
        op.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS story_hook TEXT")
        op.execute("ALTER TABLE stories ADD COLUMN IF NOT EXISTS chapters_data JSONB")
        return

    json_type = _json_type()
    if not _has_column("stories", "ideation_stage"):
        op.add_column("stories", sa.Column("ideation_stage", sa.String(64), nullable=True))
    if not _has_column("stories", "ideation_chat_data"):
        op.add_column("stories", sa.Column("ideation_chat_data", json_type, nullable=True))
    if not _has_column("stories", "ideation_research_data"):
        op.add_column("stories", sa.Column("ideation_research_data", json_type, nullable=True))
    if not _has_column("stories", "story_hook"):
        op.add_column("stories", sa.Column("story_hook", sa.Text(), nullable=True))
    if not _has_column("stories", "chapters_data"):
        op.add_column("stories", sa.Column("chapters_data", json_type, nullable=True))


def downgrade() -> None:
    if _is_postgres():
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS chapters_data")
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS story_hook")
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS ideation_research_data")
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS ideation_chat_data")
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS ideation_stage")
        return

    for column_name in (
        "chapters_data",
        "story_hook",
        "ideation_research_data",
        "ideation_chat_data",
        "ideation_stage",
    ):
        if _has_column("stories", column_name):
            op.drop_column("stories", column_name)
