"""Add persistent incremental meal coverage state.

Revision ID: a4c8d2e6f0b1
Revises: 9e2f4a6b8c1d
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "a4c8d2e6f0b1"
down_revision: Union[str, Sequence[str], None] = "9e2f4a6b8c1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if "meal_coverage_states" in inspector.get_table_names():
            return
    op.create_table(
        "meal_coverage_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("meal_key", sa.String(length=64), nullable=False),
        sa.Column("external_meal_id", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("current_revision", sa.String(length=64), nullable=False),
        sa.Column("current_nutrition", sa.JSON(), nullable=False),
        sa.Column("covered_nutrition", sa.JSON(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("last_confirmed_bolus", sa.Float(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_calculation_id", sa.String(length=64), nullable=True),
        sa.Column("last_treatment_id", sa.String(), nullable=True),
        sa.Column("confirmation_in_progress_id", sa.String(length=64), nullable=True),
        sa.Column("confirmation_in_progress_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "meal_key", name="uq_meal_coverage_user_key"),
    )
    op.create_index("ix_meal_coverage_states_user_id", "meal_coverage_states", ["user_id"])
    op.create_index("ix_meal_coverage_states_meal_key", "meal_coverage_states", ["meal_key"])
    op.create_index(
        "ix_meal_coverage_states_last_calculation_id",
        "meal_coverage_states",
        ["last_calculation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_meal_coverage_states_last_calculation_id", table_name="meal_coverage_states")
    op.drop_index("ix_meal_coverage_states_meal_key", table_name="meal_coverage_states")
    op.drop_index("ix_meal_coverage_states_user_id", table_name="meal_coverage_states")
    op.drop_table("meal_coverage_states")
