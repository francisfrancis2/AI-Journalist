"""Add Idea Generator V2 persistence and handoff lineage.

Revision ID: 0020
Revises: 0019
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "idea_generation_runs",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("geography", sa.String(8), nullable=False, server_default="AE"),
        sa.Column("trend_window_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(64), nullable=False, server_default="queued"),
        sa.Column("stage_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_level", sa.String(16), nullable=False, server_default="partial"),
        sa.Column("coverage_reasons", sa.JSON(), nullable=False),
        sa.Column("provider_statuses", sa.JSON(), nullable=False),
        sa.Column("candidate_metrics", sa.JSON(), nullable=False),
        sa.Column("usage_metrics", sa.JSON(), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False, server_default="v2"),
        sa.Column("prompt_version", sa.String(32), nullable=False, server_default="idea-generator-v2"),
        sa.Column("previous_run_id", uuid_type, nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_idea_runs_user_idempotency"),
    )
    op.create_index("ix_idea_generation_runs_user_id", "idea_generation_runs", ["user_id"])
    op.create_index("ix_idea_generation_runs_status", "idea_generation_runs", ["status"])

    op.create_table(
        "generated_ideas",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("run_id", uuid_type, sa.ForeignKey("idea_generation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("sector", sa.String(120), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("premise", sa.Text(), nullable=False),
        sa.Column("why_now", sa.Text(), nullable=False),
        sa.Column("uae_relevance", sa.Text(), nullable=False),
        sa.Column("central_tension", sa.Text(), nullable=False),
        sa.Column("target_audience", sa.String(300), nullable=False),
        sa.Column("business_significance", sa.Text(), nullable=False),
        sa.Column("format_details", sa.JSON(), nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("strength", sa.String(24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("verification_gaps", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="active"),
        sa.Column("story_id", uuid_type, nullable=True),
        sa.Column("research_session_id", uuid_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_generated_ideas_run_id", "generated_ideas", ["run_id"])

    op.create_table(
        "idea_sources",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("run_id", uuid_type, sa.ForeignKey("idea_generation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=False, server_default="en"),
        sa.Column("credibility", sa.String(24), nullable=False, server_default="medium"),
        sa.Column("is_uae_relevant", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_idea_sources_run_id", "idea_sources", ["run_id"])

    op.create_table(
        "idea_signals",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("run_id", uuid_type, sa.ForeignKey("idea_generation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("geography", sa.String(16), nullable=True),
        sa.Column("geography_meaning", sa.String(255), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_days", sa.Integer(), nullable=True),
        sa.Column("metric", sa.String(64), nullable=True),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("reliability", sa.String(24), nullable=False, server_default="medium"),
        sa.Column("is_cached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_reference", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_idea_signals_run_id", "idea_signals", ["run_id"])

    op.create_table(
        "idea_source_links",
        sa.Column("idea_id", uuid_type, sa.ForeignKey("generated_ideas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_id", uuid_type, sa.ForeignKey("idea_sources.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "idea_signal_links",
        sa.Column("idea_id", uuid_type, sa.ForeignKey("generated_ideas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("signal_id", uuid_type, sa.ForeignKey("idea_signals.id", ondelete="CASCADE"), primary_key=True),
    )

    op.add_column("stories", sa.Column("origin_idea_id", uuid_type, nullable=True))
    op.add_column("stories", sa.Column("research_mode", sa.String(32), nullable=True))
    op.add_column("stories", sa.Column("seed_research_data", sa.JSON(), nullable=True))
    op.create_index("ix_stories_origin_idea_id", "stories", ["origin_idea_id"])
    op.add_column("research_sessions", sa.Column("origin_idea_id", uuid_type, nullable=True))
    op.add_column("research_sessions", sa.Column("seed_evidence_data", sa.JSON(), nullable=True))
    op.create_index("ix_research_sessions_origin_idea_id", "research_sessions", ["origin_idea_id"])


def downgrade() -> None:
    op.drop_index("ix_research_sessions_origin_idea_id", table_name="research_sessions")
    op.drop_column("research_sessions", "seed_evidence_data")
    op.drop_column("research_sessions", "origin_idea_id")
    op.drop_index("ix_stories_origin_idea_id", table_name="stories")
    op.drop_column("stories", "seed_research_data")
    op.drop_column("stories", "research_mode")
    op.drop_column("stories", "origin_idea_id")
    op.drop_table("idea_signal_links")
    op.drop_table("idea_source_links")
    op.drop_table("idea_signals")
    op.drop_table("idea_sources")
    op.drop_table("generated_ideas")
    op.drop_table("idea_generation_runs")
