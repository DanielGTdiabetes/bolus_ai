"""Set auto_apply_safe default false.

Revision ID: set_auto_apply_safe_default_false
Revises: 1eb17937698e
Create Date: 2026-03-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "set_auto_apply_safe_default_false"
down_revision: Union[str, Sequence[str], None] = "1eb17937698e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if table_name not in inspector.get_table_names():
        return False
    columns = {col["name"] for col in inspector.get_columns(table_name)}
    return column_name in columns


def upgrade() -> None:
    """Upgrade schema."""
    if not _column_exists("user_settings", "auto_apply_safe"):
        return

    op.alter_column(
        "user_settings",
        "auto_apply_safe",
        existing_type=sa.Boolean(),
        server_default=sa.text("false"),
    )
    op.execute(sa.text("UPDATE user_settings SET auto_apply_safe = false WHERE auto_apply_safe IS NULL"))


def downgrade() -> None:
    """Downgrade schema."""
    if not _column_exists("user_settings", "auto_apply_safe"):
        return

    op.alter_column(
        "user_settings",
        "auto_apply_safe",
        existing_type=sa.Boolean(),
        server_default=sa.text("true"),
    )
