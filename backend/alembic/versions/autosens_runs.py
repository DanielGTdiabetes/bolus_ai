"""Add autosens runs table

Revision ID: autosens_runs
Revises: night_pattern_profiles
Create Date: 2026-03-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "autosens_runs"
down_revision = "night_pattern_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    from sqlalchemy import inspect
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "autosens_runs" not in tables:
        op.create_table(
            "autosens_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ratio", sa.Float(), nullable=False),
            sa.Column("window_hours", sa.Integer(), nullable=False),
            sa.Column("input_summary_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
            sa.Column("clamp_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("reason_flags", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
            sa.Column("enabled_state", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.create_index(op.f("ix_autosens_runs_user_id"), "autosens_runs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_autosens_runs_user_id"), table_name="autosens_runs")
    op.drop_table("autosens_runs")
