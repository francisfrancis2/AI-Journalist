"""Add story generation options and managed auth columns

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        op.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
        )
        op.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE"
        )
        op.execute(
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS target_duration_minutes INTEGER NOT NULL DEFAULT 12"
        )
        op.execute(
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS target_audience VARCHAR(256)"
        )
    else:
        op.add_column(
            "users",
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.add_column(
            "users",
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.add_column(
            "stories",
            sa.Column("target_duration_minutes", sa.Integer(), nullable=False, server_default="12"),
        )
        op.add_column("stories", sa.Column("target_audience", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("stories", "target_audience")
    op.drop_column("stories", "target_duration_minutes")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "is_admin")
