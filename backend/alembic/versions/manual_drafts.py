"""Add nutrition_drafts table

Revision ID: manual_drafts
Revises: 
Create Date: 2026-01-06 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'manual_drafts'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('nutrition_drafts',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('user_id', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('carbs', sa.Float(), nullable=True),
    sa.Column('fat', sa.Float(), nullable=True),
    sa.Column('protein', sa.Float(), nullable=True),
    sa.Column('fiber', sa.Float(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_hash', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_nutrition_drafts_user_id'), 'nutrition_drafts', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_nutrition_drafts_user_id'), table_name='nutrition_drafts')
    op.drop_table('nutrition_drafts')
