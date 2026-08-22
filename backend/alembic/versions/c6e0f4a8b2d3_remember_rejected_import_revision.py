"""Remember rejected imported-meal source revisions.

Revision ID: c6e0f4a8b2d3
Revises: b5d9e3f7a1c2
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "c6e0f4a8b2d3"
down_revision: Union[str, Sequence[str], None] = "b5d9e3f7a1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        columns = {column["name"] for column in inspector.get_columns("imported_meals")}
        if "rejected_source_fingerprint" in columns:
            return
    op.add_column(
        "imported_meals",
        sa.Column("rejected_source_fingerprint", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        columns = {column["name"] for column in inspector.get_columns("imported_meals")}
        if "rejected_source_fingerprint" not in columns:
            return
    op.drop_column("imported_meals", "rejected_source_fingerprint")
