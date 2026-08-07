"""Add persistent companion episodes and preferences.

Revision ID: 7c9d1e2f3a4b
Revises: 2f3a4b5c6d7e
Create Date: 2026-08-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c9d1e2f3a4b"
down_revision: Union[str, Sequence[str], None] = "2f3a4b5c6d7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companion_episodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("route", sa.String(length=120), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_companion_episode_fingerprint"),
    )
    op.create_index("ix_companion_episodes_user_id", "companion_episodes", ["user_id"])
    op.create_index("ix_companion_episodes_kind", "companion_episodes", ["kind"])
    op.create_index("ix_companion_episodes_status", "companion_episodes", ["status"])
    op.create_table(
        "companion_preferences",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="balanced"),
        sa.Column("quiet_hours_start", sa.String(length=5), nullable=False, server_default="23:00"),
        sa.Column("quiet_hours_end", sa.String(length=5), nullable=False, server_default="07:00"),
        sa.Column("repeat_critical_minutes", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("repeat_high_minutes", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("companion_preferences")
    op.drop_index("ix_companion_episodes_status", table_name="companion_episodes")
    op.drop_index("ix_companion_episodes_kind", table_name="companion_episodes")
    op.drop_index("ix_companion_episodes_user_id", table_name="companion_episodes")
    op.drop_table("companion_episodes")
