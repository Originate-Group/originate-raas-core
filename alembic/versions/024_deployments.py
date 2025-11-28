"""Add Deployment table for multi-environment tracking.

Revision ID: 024_deployments
Revises: 023_release_work_items
Create Date: 2025-11-28

RAAS-FEAT-103: Multi-Environment Deployment Tracking

This migration implements:
- Environment enum (dev, staging, prod)
- DeploymentStatus enum (pending, deploying, success, failed, rolled_back)
- Deployments table tracking release deployments per environment
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '024_deployments'
down_revision = '023_release_work_items'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ==========================================================================
    # Create Environment enum
    # ==========================================================================
    environment_enum = postgresql.ENUM('dev', 'staging', 'prod', name='environment')
    environment_enum.create(op.get_bind(), checkfirst=True)

    # ==========================================================================
    # Create DeploymentStatus enum
    # ==========================================================================
    deployment_status_enum = postgresql.ENUM(
        'pending', 'deploying', 'success', 'failed', 'rolled_back',
        name='deploymentstatus'
    )
    deployment_status_enum.create(op.get_bind(), checkfirst=True)

    # ==========================================================================
    # Create deployments table
    # ==========================================================================
    op.create_table(
        'deployments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('release_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('work_items.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('environment', environment_enum, nullable=False, index=True),
        sa.Column('status', deployment_status_enum, nullable=False,
                  server_default='pending', index=True),
        sa.Column('artifact_ref', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('now()'),
                  nullable=False, index=True),
        sa.Column('deployed_at', sa.DateTime, nullable=True),
        sa.Column('rolled_back_at', sa.DateTime, nullable=True),
        sa.Column('deployed_by_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('release_id', 'environment',
                            name='uq_deployment_release_environment'),
    )


def downgrade() -> None:
    # Drop deployments table
    op.drop_table('deployments')

    # Drop enums
    op.execute("DROP TYPE IF EXISTS deploymentstatus")
    op.execute("DROP TYPE IF EXISTS environment")
