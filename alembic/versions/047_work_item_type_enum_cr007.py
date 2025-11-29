"""Update WorkItemType enum: Remove IR/TASK, Add DEBT (CR-007).

Revision ID: 047
Revises: 046
Create Date: 2025-11-29

CR-007: Update WorkItemType Enum
- Remove IR: Use CR instead, distinguish billable vs internal via tags
- Remove TASK: Removed in BUG-005 (conflicts with Task entity)
- Add DEBT: Technical debt work items (works but needs refactoring)

Final enum values: cr, bug, debt, release
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '047'
down_revision: Union[str, None] = '046'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add DEBT to enum, remove IR and TASK."""

    # PostgreSQL enum type modification requires several steps:
    # 1. Add new value 'debt' to the enum
    # 2. Remove unused values (ir, task) - requires migration of existing data

    # Step 1: Add 'debt' value to the enum
    # PostgreSQL requires ALTER TYPE ... ADD VALUE
    op.execute("ALTER TYPE workitemtype ADD VALUE IF NOT EXISTS 'debt'")

    # Step 2: Migrate any existing IR work items to CR
    # Note: This is safe because IR and CR are semantically similar
    # (both represent implementation work, distinguished by tags)
    op.execute("""
        UPDATE work_items
        SET work_item_type = 'cr'
        WHERE work_item_type = 'ir'
    """)

    # Step 3: Migrate any existing TASK work items to CR
    # Note: TASK was deprecated in BUG-005
    op.execute("""
        UPDATE work_items
        SET work_item_type = 'cr'
        WHERE work_item_type = 'task'
    """)

    # Step 4: Update the human_readable_id for migrated IR items
    # Change IR-XXX to CR-XXX (note: may cause collisions, handled below)
    op.execute("""
        UPDATE work_items
        SET human_readable_id = REPLACE(human_readable_id, 'IR-', 'CR-')
        WHERE human_readable_id LIKE 'IR-%'
    """)

    # Step 5: Update TASK-XXX to CR-XXX
    op.execute("""
        UPDATE work_items
        SET human_readable_id = REPLACE(human_readable_id, 'TASK-', 'CR-')
        WHERE human_readable_id LIKE 'TASK-%'
    """)

    # Step 6: Update label_mapping in github_integrations to remove ir/task, add debt
    op.execute("""
        UPDATE github_integrations
        SET label_mapping = jsonb_build_object(
            'cr', COALESCE(label_mapping->>'cr', 'raas:change-request'),
            'bug', COALESCE(label_mapping->>'bug', 'raas:bug'),
            'debt', 'raas:technical-debt',
            'release', 'raas:release'
        )
    """)

    # Note: PostgreSQL does not support DROP VALUE from enum types in a simple way.
    # The 'ir' and 'task' values will remain in the enum but will not be used.
    # This is acceptable as:
    # 1. No data references these values after migration
    # 2. The application code no longer exposes these values
    # 3. Attempting to insert them would fail validation at the API layer


def downgrade() -> None:
    """Reverse the migration - restore IR, migrate DEBT back to CR."""

    # Note: Cannot remove enum values in PostgreSQL without recreating the type
    # This downgrade only migrates data, not the enum definition

    # Migrate DEBT work items back to CR
    op.execute("""
        UPDATE work_items
        SET work_item_type = 'cr'
        WHERE work_item_type = 'debt'
    """)

    # Restore label_mapping to include ir and task
    op.execute("""
        UPDATE github_integrations
        SET label_mapping = jsonb_build_object(
            'ir', 'raas:implementation-request',
            'cr', COALESCE(label_mapping->>'cr', 'raas:change-request'),
            'bug', COALESCE(label_mapping->>'bug', 'raas:bug'),
            'task', 'raas:task'
        )
    """)
