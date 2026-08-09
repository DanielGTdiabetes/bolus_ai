"""Add canonical glucose readings.

Revision ID: 8d1f2a3b4c5d
Revises: 7c9d1e2f3a4b
Create Date: 2026-08-09 19:30:00.000000
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "8d1f2a3b4c5d"
down_revision: Union[str, Sequence[str], None] = "7c9d1e2f3a4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Runtime deploys are idempotent; offline SQL generation has no inspectable
    # connection and should always emit the additive DDL.
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if "glucose_readings" in inspector.get_table_names():
            return

    op.create_table(
        "glucose_readings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("reading_uid", sa.String(length=160), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("glucose_mgdl", sa.Integer(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at_watch", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at_phone", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_package", sa.String(length=160), nullable=True),
        sa.Column("origin_installation_id", sa.String(length=160), nullable=True),
        sa.Column("sensor_type", sa.String(length=40), nullable=True),
        sa.Column("sensor_session_id", sa.String(length=160), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("outbox_sequence", sa.Integer(), nullable=True),
        sa.Column("trend_arrow", sa.String(length=64), nullable=True),
        sa.Column("trend_rate", sa.Float(), nullable=True),
        sa.Column("sensor_state", sa.String(length=64), nullable=True),
        sa.Column("display_only", sa.Boolean(), nullable=False),
        sa.Column("historical", sa.Boolean(), nullable=False),
        sa.Column("timestamp_uncertain", sa.Boolean(), nullable=False),
        sa.Column("validation_status", sa.String(length=24), nullable=False),
        sa.Column("validation_reason", sa.String(length=160), nullable=True),
        sa.Column("usable_for_dosing", sa.Boolean(), nullable=False),
        sa.Column("decision_eligible", sa.Boolean(), nullable=False),
        sa.Column("sync_status", sa.String(length=24), nullable=False),
        sa.Column("sync_attempts", sa.Integer(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "reading_uid", name="uq_glucose_reading_user_uid"),
        sa.UniqueConstraint(
            "user_id",
            "source",
            "origin_installation_id",
            "sensor_session_id",
            "sequence",
            name="uq_glucose_reading_sensor_sequence",
        ),
    )
    op.create_index("ix_glucose_readings_user_id", "glucose_readings", ["user_id"])
    op.create_index(
        "ix_glucose_readings_user_measured",
        "glucose_readings",
        ["user_id", "measured_at"],
    )
    op.create_index(
        "ix_glucose_readings_user_source_measured",
        "glucose_readings",
        ["user_id", "source", "measured_at"],
    )
    op.create_index(
        "ix_glucose_readings_sync_status",
        "glucose_readings",
        ["sync_status", "received_at"],
    )


def downgrade() -> None:
    op.drop_table("glucose_readings")
