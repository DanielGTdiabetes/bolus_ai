"""Compatibility marker for CLIN-001 nutrition event identities.

This revision is intentionally non-operative. It preserves Alembic graph
continuity for databases that already recorded ``clin001_nutrition_id`` while
keeping the post-PR-155 rollback from applying any CLIN-001 DDL.
"""

revision = "clin001_nutrition_id"
down_revision = "2f3a4b5c6d7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
