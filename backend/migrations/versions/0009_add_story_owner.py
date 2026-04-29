"""Add story owner column

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgres():
        op.execute(
            "ALTER TABLE stories ADD COLUMN IF NOT EXISTS owner_user_id UUID"
        )
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'fk_stories_owner_user_id_users'
                ) THEN
                    ALTER TABLE stories
                    ADD CONSTRAINT fk_stories_owner_user_id_users
                    FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL;
                END IF;
            END $$;
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_stories_owner_user_id ON stories (owner_user_id)"
        )
    else:
        try:
            op.add_column("stories", sa.Column("owner_user_id", sa.String(36), nullable=True))
        except Exception:
            pass
        try:
            op.create_index("ix_stories_owner_user_id", "stories", ["owner_user_id"], unique=False)
        except Exception:
            pass


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP INDEX IF EXISTS ix_stories_owner_user_id")
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'fk_stories_owner_user_id_users'
                ) THEN
                    ALTER TABLE stories
                    DROP CONSTRAINT fk_stories_owner_user_id_users;
                END IF;
            END $$;
            """
        )
        op.execute("ALTER TABLE stories DROP COLUMN IF EXISTS owner_user_id")
    else:
        try:
            op.drop_index("ix_stories_owner_user_id", table_name="stories")
        except Exception:
            pass
        op.drop_column("stories", "owner_user_id")
