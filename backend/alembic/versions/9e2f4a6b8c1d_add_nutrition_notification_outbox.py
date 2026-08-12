"""Add the persistent nutrition notification outbox.

Revision ID: 9e2f4a6b8c1d
Revises: 8d1f2a3b4c5d
Create Date: 2026-08-12 10:30:00.000000
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "9e2f4a6b8c1d"
down_revision: Union[str, Sequence[str], None] = "8d1f2a3b4c5d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if "nutrition_notification_outbox" in inspector.get_table_names():
            return

    op.create_table(
        "nutrition_notification_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("notification_kind", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("sync_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_message_id", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "notification_kind",
            "channel",
            name="uq_nutrition_notification_event_kind_channel",
        ),
    )
    op.create_index(
        "ix_nutrition_notification_outbox_event_id",
        "nutrition_notification_outbox",
        ["event_id"],
    )
    op.create_index(
        "ix_nutrition_notification_outbox_sync_id",
        "nutrition_notification_outbox",
        ["sync_id"],
    )
    op.create_index(
        "ix_nutrition_notification_pending",
        "nutrition_notification_outbox",
        ["status", "next_attempt_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("nutrition_notification_outbox")
