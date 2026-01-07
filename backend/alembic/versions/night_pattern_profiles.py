"""Add night pattern profiles table

Revision ID: night_pattern_profiles
Revises: manual_drafts
Create Date: 2026-02-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "night_pattern_profiles"
down_revision = "manual_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    try:
        op.create_table(
            "night_pattern_profiles",
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("bucket_minutes", sa.Integer(), nullable=False),
            sa.Column("horizon_minutes", sa.Integer(), nullable=False),
            sa.Column("sample_days", sa.Integer(), nullable=False),
            sa.Column("sample_points", sa.Integer(), nullable=False),
            sa.Column("pattern", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dispersion_iqr", sa.Float(), nullable=True),
            sa.PrimaryKeyConstraint("user_id"),
        )
    except Exception:
        pass


def downgrade() -> None:
    op.drop_table("night_pattern_profiles")
