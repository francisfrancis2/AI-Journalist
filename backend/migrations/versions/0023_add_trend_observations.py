"""Pool UAE trend research across runs, and keep the deep-research narrative.

Research was stored per run and cascaded away with it, so a deleted run took
its research with it -- and the deep-research narrative, the richest artefact a
run produces, was never stored at all. ``trend_observations`` is keyed by
content rather than by run, so research accumulates across every user and
survives the run that found it. Each new generation can then build on what is
already known instead of re-fetching it.

Revision ID: 0023
Revises: 0022
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "idea_generation_runs",
        sa.Column("deep_research_report", sa.Text(), nullable=True),
    )
    op.create_table(
        "trend_observations",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credibility", sa.String(length=24), nullable=False, server_default="medium"),
        sa.Column("is_uae_relevant", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default="1"),
    )
    # Unique: the upsert key. Indexed separately for the retention sweep and
    # for the recency-ranked read-back.
    op.create_unique_constraint(
        "uq_trend_observations_content_hash", "trend_observations", ["content_hash"]
    )
    op.create_index(
        "ix_trend_observations_last_seen_at", "trend_observations", ["last_seen_at"]
    )
    op.create_index("ix_trend_observations_kind", "trend_observations", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_trend_observations_kind", table_name="trend_observations")
    op.drop_index("ix_trend_observations_last_seen_at", table_name="trend_observations")
    op.drop_constraint(
        "uq_trend_observations_content_hash", "trend_observations", type_="unique"
    )
    op.drop_table("trend_observations")
    op.drop_column("idea_generation_runs", "deep_research_report")
