"""Fix WorkItem HRID trigger and migrate stale IR records (BUG-012).

Revision ID: 048
Revises: 047
Create Date: 2025-11-29

BUG-012: DEBT work items incorrectly slugged as WI-nnn instead of DEBT-nnn

Root Cause:
- Migration 022 created trigger with only ir/cr/bug/task cases
- Migration 047 added 'debt' and 'release' to enum but didn't update trigger
- Trigger falls through to ELSE clause, using 'WI' prefix for unknown types

This migration:
1. Updates trigger to handle 'debt' -> 'DEBT' and 'release' -> 'REL'
2. Migrates any remaining 'ir' records to 'cr' (047 migration may have failed)
3. Fixes existing WI-002 HRID to DEBT-001
4. Fixes IR-001 HRID to CR-XXX (next available)
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '048'
down_revision: Union[str, None] = '047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix HRID trigger and migrate stale data."""

    # Step 1: Update the trigger function to handle all current work item types
    op.execute("""
        CREATE OR REPLACE FUNCTION generate_work_item_human_readable_id()
        RETURNS TRIGGER AS $$
        DECLARE
            type_prefix TEXT;
            next_num INTEGER;
        BEGIN
            -- Determine prefix based on work item type
            -- Updated for CR-007: removed ir/task, added debt/release
            CASE NEW.work_item_type
                WHEN 'cr' THEN type_prefix := 'CR';
                WHEN 'bug' THEN type_prefix := 'BUG';
                WHEN 'debt' THEN type_prefix := 'DEBT';
                WHEN 'release' THEN type_prefix := 'REL';
                ELSE type_prefix := 'WI';  -- Fallback for any future types
            END CASE;

            -- Get or create sequence for this org + type
            INSERT INTO id_sequences (project_id, requirement_type, next_number)
            VALUES (
                COALESCE(NEW.project_id, '00000000-0000-0000-0000-000000000000'::uuid),
                'work_item_' || NEW.work_item_type,
                1
            )
            ON CONFLICT (project_id, requirement_type) DO UPDATE
            SET next_number = id_sequences.next_number + 1,
                updated_at = NOW()
            RETURNING next_number INTO next_num;

            -- Generate human-readable ID
            NEW.human_readable_id := type_prefix || '-' || LPAD(next_num::TEXT, 3, '0');

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Step 2: Migrate any remaining 'ir' work items to 'cr'
    # This should have been done in 047 but may have failed
    op.execute("""
        UPDATE work_items
        SET work_item_type = 'cr'
        WHERE work_item_type = 'ir'
    """)

    # Step 3: Fix HRIDs for migrated items
    # IR-XXX -> CR-XXX (preserve the number to avoid conflicts)
    op.execute("""
        UPDATE work_items
        SET human_readable_id = 'CR-' || SUBSTRING(human_readable_id FROM 4)
        WHERE human_readable_id LIKE 'IR-%'
    """)

    # Step 4: Fix WI-001 (was 'ir' type, now 'cr') - it's a test item
    # Keep as CR since it was migrated, just update HRID if still WI-
    op.execute("""
        UPDATE work_items
        SET human_readable_id = 'CR-' || SUBSTRING(human_readable_id FROM 4)
        WHERE human_readable_id LIKE 'WI-001'
          AND work_item_type = 'cr'
    """)

    # Step 5: Fix WI-002 which is type 'debt' but got WI- prefix
    # Need to rename to DEBT-001 (first debt item)
    op.execute("""
        UPDATE work_items
        SET human_readable_id = 'DEBT-001'
        WHERE human_readable_id = 'WI-002'
          AND work_item_type = 'debt'
    """)

    # Step 6: Reset the debt sequence to account for the fix
    # Next debt item should be DEBT-002
    op.execute("""
        INSERT INTO id_sequences (project_id, requirement_type, next_number)
        VALUES (
            '00000000-0000-0000-0000-000000000000'::uuid,
            'work_item_debt',
            2
        )
        ON CONFLICT (project_id, requirement_type) DO UPDATE
        SET next_number = 2,
            updated_at = NOW()
    """)


def downgrade() -> None:
    """Revert trigger to original version (not recommended)."""

    # Restore original trigger (without debt/release support)
    # Note: This will break DEBT and RELEASE work item creation
    op.execute("""
        CREATE OR REPLACE FUNCTION generate_work_item_human_readable_id()
        RETURNS TRIGGER AS $$
        DECLARE
            type_prefix TEXT;
            next_num INTEGER;
        BEGIN
            CASE NEW.work_item_type
                WHEN 'ir' THEN type_prefix := 'IR';
                WHEN 'cr' THEN type_prefix := 'CR';
                WHEN 'bug' THEN type_prefix := 'BUG';
                WHEN 'task' THEN type_prefix := 'WI';
                ELSE type_prefix := 'WI';
            END CASE;

            INSERT INTO id_sequences (project_id, requirement_type, next_number)
            VALUES (
                COALESCE(NEW.project_id, '00000000-0000-0000-0000-000000000000'::uuid),
                'work_item_' || NEW.work_item_type,
                1
            )
            ON CONFLICT (project_id, requirement_type) DO UPDATE
            SET next_number = id_sequences.next_number + 1,
                updated_at = NOW()
            RETURNING next_number INTO next_num;

            NEW.human_readable_id := type_prefix || '-' || LPAD(next_num::TEXT, 3, '0');

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Note: Data migrations (ir->cr, HRID fixes) are not reverted
    # as this would require tracking original values
