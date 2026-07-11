"""add persistent nutrition event identities

Revision ID: clin001_nutrition_id
Revises: manual_drafts
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "clin001_nutrition_id"
down_revision = "2f3a4b5c6d7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nutrition_event_identities",
        sa.Column("identity_key", sa.String(length=64), primary_key=True),
        sa.Column("treatment_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id_hash", sa.String(length=64), nullable=False),
        sa.Column("food_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("match_strategy", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_nutrition_identity_treatment", "nutrition_event_identities", ["treatment_id"])
    op.create_index("ix_nutrition_identity_user_source", "nutrition_event_identities", ["user_id", "source"])


def downgrade() -> None:
    op.drop_index("ix_nutrition_identity_user_source", table_name="nutrition_event_identities")
    op.drop_index("ix_nutrition_identity_treatment", table_name="nutrition_event_identities")
    op.drop_table("nutrition_event_identities")
