"""Add youtube_demand_data to stories and research_sessions.

Stores the vidIQ YouTube audience-demand report (keyword volumes + top videos)
so the UI can render the "YouTube Research and Analysis" panel without re-querying
vidIQ, which costs credits.

Revision ID: 0019
Revises: 0018
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stories", sa.Column("youtube_demand_data", sa.JSON(), nullable=True))
    op.add_column(
        "research_sessions", sa.Column("youtube_demand_data", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("research_sessions", "youtube_demand_data")
    op.drop_column("stories", "youtube_demand_data")
