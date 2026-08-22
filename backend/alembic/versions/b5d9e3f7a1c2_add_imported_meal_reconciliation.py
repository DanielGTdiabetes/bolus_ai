"""Add durable imported meal reconciliation records.

Revision ID: b5d9e3f7a1c2
Revises: a4c8d2e6f0b1
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "b5d9e3f7a1c2"
down_revision: Union[str, Sequence[str], None] = "a4c8d2e6f0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if "imported_meals" in inspector.get_table_names():
            return
    op.create_table(
        "imported_meals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("source_reference", sa.String(255), nullable=False),
        sa.Column("meal_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(40), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("foods", sa.JSON(), nullable=False),
        sa.Column("source_carbs", sa.Float(), nullable=False),
        sa.Column("calculated_carbs", sa.Float(), nullable=False),
        sa.Column("previous_calculated_carbs", sa.Float(), nullable=True),
        sa.Column("fat", sa.Float(), nullable=False),
        sa.Column("protein", sa.Float(), nullable=False),
        sa.Column("fiber", sa.Float(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("previous_fingerprint", sa.String(64), nullable=True),
        sa.Column("stable_read_count", sa.Integer(), nullable=False),
        sa.Column("is_stable", sa.Boolean(), nullable=False),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        sa.Column("pending_source_version", sa.JSON(), nullable=True),
        sa.Column("discarded_fingerprint", sa.String(64), nullable=True),
        sa.Column("treatment_status", sa.String(24), nullable=False),
        sa.Column("draft_treatment_id", sa.String(), nullable=True),
        sa.Column("linked_bolus_id", sa.String(), nullable=True),
        sa.Column("last_bolus_units", sa.Float(), nullable=True),
        sa.Column("last_bolus_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_message_id", sa.String(64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source", "source_reference", name="uq_imported_meal_source_reference"),
    )
    for name, columns in (
        ("ix_imported_meals_user_id", ["user_id"]),
        ("ix_imported_meals_meal_date", ["meal_date"]),
        ("ix_imported_meals_status", ["status"]),
        ("ix_imported_meal_status_seen", ["status", "last_seen_at"]),
        ("ix_imported_meals_draft_treatment_id", ["draft_treatment_id"]),
        ("ix_imported_meals_linked_bolus_id", ["linked_bolus_id"]),
    ):
        op.create_index(name, "imported_meals", columns)

    op.create_table(
        "imported_meal_snapshots",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("meal_id", sa.String(36), nullable=False),
        sa.Column("sync_id", sa.String(64), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("source_carbs", sa.Float(), nullable=False),
        sa.Column("calculated_carbs", sa.Float(), nullable=False),
        sa.Column("foods", sa.JSON(), nullable=False),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("timing", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_imported_meal_snapshots_meal_id", "imported_meal_snapshots", ["meal_id"])
    op.create_index("ix_imported_meal_snapshots_sync_id", "imported_meal_snapshots", ["sync_id"])
    op.create_index("ix_imported_meal_snapshot_meal_seen", "imported_meal_snapshots", ["meal_id", "seen_at"])


def downgrade() -> None:
    op.drop_table("imported_meal_snapshots")
    op.drop_table("imported_meals")
