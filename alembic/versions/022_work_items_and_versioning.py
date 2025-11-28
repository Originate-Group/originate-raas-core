"""Add Work Items and Requirement Versioning tables.

Revision ID: 022_work_items_and_versioning
Revises: 021_add_task_routing_rules
Create Date: 2025-11-28

CR-010: Requirement Versioning, Work Items & GitHub Integration

This migration implements:
- RAAS-COMP-075: Work Item Management
- RAAS-FEAT-097: Requirement Content Versioning
- RAAS-FEAT-098: Bidirectional Tag Linking for Work Items
- RAAS-FEAT-099: Work Item Lifecycle & CR Merge Trigger
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '022_work_items_and_versioning'
down_revision = '021_add_task_routing_rules'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # Work Item Enums
    # ==========================================================================

    # Work Item Type enum
    workitemtype = postgresql.ENUM(
        'ir',           # Implementation Request - new feature work
        'cr',           # Change Request - modifications to approved requirements
        'bug',          # Bug fix
        'task',         # General task
        name='workitemtype',
        create_type=True
    )
    workitemtype.create(op.get_bind())

    # Work Item Status enum (implementation lifecycle)
    workitemstatus = postgresql.ENUM(
        'created',      # Initial state
        'in_progress',  # Work has started
        'implemented',  # Code complete, ready for validation
        'validated',    # Testing/validation passed
        'deployed',     # Deployed to production
        'completed',    # Terminal: successfully finished
        'cancelled',    # Terminal: abandoned
        name='workitemstatus',
        create_type=True
    )
    workitemstatus.create(op.get_bind())

    # ==========================================================================
    # Work Items Table (RAAS-COMP-075)
    # ==========================================================================
    op.create_table(
        'work_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('human_readable_id', sa.String(20), unique=True, nullable=True, index=True),

        # Scope
        sa.Column('organization_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'),
                  nullable=True, index=True),

        # Core fields
        sa.Column('work_item_type', workitemtype, nullable=False, index=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('status', workitemstatus, nullable=False, default='created', index=True),
        sa.Column('priority', sa.String(20), nullable=False, default='medium'),

        # Assignment
        sa.Column('assigned_to', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True, index=True),

        # CR-specific: proposed content for requirements (RAAS-FEAT-099)
        # Structure: {requirement_id: "new markdown content"}
        sa.Column('proposed_content', postgresql.JSONB, nullable=True),
        # Structure: {requirement_id: "content_hash"} - for conflict detection
        sa.Column('baseline_hashes', postgresql.JSONB, nullable=True),

        # Implementation references (GitHub PRs, commits, releases)
        # Structure: {github_issue_url, pr_urls: [], commit_shas: [], release_tag}
        sa.Column('implementation_refs', postgresql.JSONB, nullable=True, default=dict),

        # Tags for bidirectional linking (RAAS-FEAT-098)
        sa.Column('tags', postgresql.ARRAY(sa.String), default=[]),

        # Audit fields
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()'), nullable=False, index=True),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_by_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),

        # Completion tracking
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('cancelled_at', sa.DateTime, nullable=True),
    )

    # Index for finding work items by type and status
    op.create_index(
        'ix_work_items_type_status',
        'work_items',
        ['work_item_type', 'status']
    )

    # ==========================================================================
    # Work Item Affects Association Table (RAAS-FEAT-098)
    # Links Work Items to affected requirements
    # ==========================================================================
    op.create_table(
        'work_item_affects',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('work_item_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('work_items.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('requirement_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('requirements.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('work_item_id', 'requirement_id', name='uq_work_item_affects_requirement'),
    )

    # ==========================================================================
    # Requirement Versions Table (RAAS-FEAT-097)
    # Immutable snapshots of requirement content
    # ==========================================================================
    op.create_table(
        'requirement_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('requirement_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('requirements.id', ondelete='CASCADE'),
                  nullable=False, index=True),

        # Version tracking
        sa.Column('version_number', sa.Integer, nullable=False),

        # Content snapshot (immutable)
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),  # SHA-256 hex

        # Title and description snapshot (for quick reference)
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),

        # Source tracking - what caused this version
        sa.Column('source_work_item_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('work_items.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('change_reason', sa.Text, nullable=True),

        # Audit
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()'), nullable=False, index=True),
        sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),

        # Unique constraint: one version number per requirement
        sa.UniqueConstraint('requirement_id', 'version_number', name='uq_requirement_version_number'),
    )

    # Index for efficient version lookups
    op.create_index(
        'ix_requirement_versions_req_version',
        'requirement_versions',
        ['requirement_id', 'version_number']
    )

    # ==========================================================================
    # Add current_version_id to requirements table
    # ==========================================================================
    op.add_column(
        'requirements',
        sa.Column('current_version_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('requirement_versions.id', ondelete='SET NULL'),
                  nullable=True)
    )

    # Add content_hash to requirements for conflict detection
    op.add_column(
        'requirements',
        sa.Column('content_hash', sa.String(64), nullable=True)
    )

    # ==========================================================================
    # Work Item History Table (audit trail)
    # ==========================================================================
    op.create_table(
        'work_item_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('work_item_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('work_items.id', ondelete='CASCADE'),
                  nullable=False, index=True),

        # Change details
        sa.Column('change_type', sa.String(50), nullable=False),  # created, status_changed, assigned, etc.
        sa.Column('field_name', sa.String(100), nullable=True),
        sa.Column('old_value', sa.Text, nullable=True),
        sa.Column('new_value', sa.Text, nullable=True),

        # Audit
        sa.Column('changed_by_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('changed_at', sa.DateTime, server_default=sa.text('now()'), nullable=False, index=True),
        sa.Column('change_reason', sa.Text, nullable=True),
    )

    # ==========================================================================
    # ID Sequence for Work Items
    # ==========================================================================
    # Add work item types to id_sequences capability
    # Work items use org-level sequences: WI-001, CR-001, IR-001, BUG-001

    # Create trigger function for work item human-readable ID generation
    op.execute("""
        CREATE OR REPLACE FUNCTION generate_work_item_human_readable_id()
        RETURNS TRIGGER AS $$
        DECLARE
            org_slug TEXT;
            type_prefix TEXT;
            next_num INTEGER;
        BEGIN
            -- Get organization slug (not used in work item IDs, but kept for consistency)
            -- Work items use type-based prefixes: IR, CR, BUG, WI (for task)

            -- Determine prefix based on work item type
            CASE NEW.work_item_type
                WHEN 'ir' THEN type_prefix := 'IR';
                WHEN 'cr' THEN type_prefix := 'CR';
                WHEN 'bug' THEN type_prefix := 'BUG';
                WHEN 'task' THEN type_prefix := 'WI';
                ELSE type_prefix := 'WI';
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

    # Create trigger
    op.execute("""
        CREATE TRIGGER trigger_generate_work_item_hrid
        BEFORE INSERT ON work_items
        FOR EACH ROW
        WHEN (NEW.human_readable_id IS NULL)
        EXECUTE FUNCTION generate_work_item_human_readable_id();
    """)

    # ==========================================================================
    # GitHub Configuration Table (RAAS-FEAT-043)
    # ==========================================================================

    # GitHub auth type enum
    githubauthtype = postgresql.ENUM(
        'pat',          # Personal Access Token
        'github_app',   # GitHub App installation
        name='githubauthtype',
        create_type=True
    )
    githubauthtype.create(op.get_bind())

    op.create_table(
        'github_configurations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('project_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'),
                  nullable=False, unique=True, index=True),

        # Repository info
        sa.Column('repository_owner', sa.String(100), nullable=False),
        sa.Column('repository_name', sa.String(100), nullable=False),

        # Authentication
        sa.Column('auth_type', githubauthtype, nullable=False, default='pat'),
        sa.Column('encrypted_credentials', sa.LargeBinary, nullable=True),

        # Webhook configuration
        sa.Column('webhook_secret_encrypted', sa.LargeBinary, nullable=True),
        sa.Column('webhook_id', sa.String(50), nullable=True),

        # Label mapping for Work Item types
        sa.Column('label_mapping', postgresql.JSONB, nullable=False,
                  server_default='{"ir": "raas:implementation-request", "cr": "raas:change-request", "bug": "raas:bug", "task": "raas:task"}'),

        # Sync settings
        sa.Column('auto_create_issues', sa.Boolean, nullable=False, default=True),
        sa.Column('sync_pr_status', sa.Boolean, nullable=False, default=True),
        sa.Column('sync_releases', sa.Boolean, nullable=False, default=True),

        # Status
        sa.Column('is_active', sa.Boolean, nullable=False, default=True),
        sa.Column('last_sync_at', sa.DateTime, nullable=True),
        sa.Column('last_error', sa.Text, nullable=True),

        # Audit
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade() -> None:
    # Drop GitHub configuration
    op.drop_table('github_configurations')
    op.execute('DROP TYPE IF EXISTS githubauthtype')

    # Drop trigger and function
    op.execute('DROP TRIGGER IF EXISTS trigger_generate_work_item_hrid ON work_items')
    op.execute('DROP FUNCTION IF EXISTS generate_work_item_human_readable_id()')

    # Remove columns from requirements
    op.drop_column('requirements', 'content_hash')
    op.drop_column('requirements', 'current_version_id')

    # Drop tables
    op.drop_table('work_item_history')
    op.drop_table('requirement_versions')
    op.drop_table('work_item_affects')
    op.drop_index('ix_work_items_type_status', table_name='work_items')
    op.drop_table('work_items')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS workitemstatus')
    op.execute('DROP TYPE IF EXISTS workitemtype')
