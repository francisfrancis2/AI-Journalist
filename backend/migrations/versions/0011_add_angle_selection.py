"""Add angle selection columns to stories

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    # angles_data: list of {angle: str, framing_axis: str} objects produced by the
    # merged analyst/angle step. selected_angle: the angle the user picked, also
    # echoed into the scriptwriter and storyline_creator prompts as the
    # primary creative directive.
    if _is_postgres():
        op.add_column(
            "stories",
            sa.Column("angles_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    else:
        op.add_column(
            "stories",
            sa.Column("angles_data", sa.JSON(), nullable=True),
        )
    op.add_column(
        "stories",
        sa.Column("selected_angle", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stories", "selected_angle")
    op.drop_column("stories", "angles_data")
