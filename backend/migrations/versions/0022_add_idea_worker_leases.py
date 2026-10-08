"""Add durable worker ownership to Idea Generator runs.

The web app can run V1 and V2 against the same database. Previously, either
backend marked every active Idea run as interrupted whenever it started,
including healthy work owned by the other backend. Worker leases make claiming,
heartbeats, restart recovery, and terminal writes ownership-aware.

Revision ID: 0022
Revises: 0021
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "idea_generation_runs",
        sa.Column("worker_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "idea_generation_runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "idea_generation_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "idea_generation_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_idea_generation_runs_worker_id",
        "idea_generation_runs",
        ["worker_id"],
    )
    op.create_index(
        "ix_idea_generation_runs_lease_expires_at",
        "idea_generation_runs",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_idea_generation_runs_lease_expires_at",
        table_name="idea_generation_runs",
    )
    op.drop_index(
        "ix_idea_generation_runs_worker_id",
        table_name="idea_generation_runs",
    )
    op.drop_column("idea_generation_runs", "attempt_count")
    op.drop_column("idea_generation_runs", "lease_expires_at")
    op.drop_column("idea_generation_runs", "heartbeat_at")
    op.drop_column("idea_generation_runs", "worker_id")
