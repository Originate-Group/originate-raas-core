"""Add category column to acceptance_criteria (CR-017).

Revision ID: 053
Revises: 052
Create Date: 2025-11-30

Adds category column to store the subsection header each AC belongs to.
This preserves the author's organizational structure (e.g., "AC Entity Structure",
"Version Transition Behavior") when ACs are extracted from content and
injected back on read.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '053'
down_revision: Union[str, None] = '052'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add category column to acceptance_criteria."""
    op.add_column(
        'acceptance_criteria',
        sa.Column('category', sa.String(255), nullable=True)
    )


def downgrade() -> None:
    """Remove category column."""
    op.drop_column('acceptance_criteria', 'category')
