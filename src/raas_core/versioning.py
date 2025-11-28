"""Requirement versioning utilities (CR-002: RAAS-FEAT-097).

Implements git-like immutable versioning where every content change creates a new
RequirementVersion record. Versions are pure snapshots without their own status.
The Requirement's status (draft -> review -> approved) controls the approval workflow.

Key concepts:
- current_version_id: Points to the approved/active specification
- deployed_version_id: Points to what's actually in production
- Modifying approved content regresses status to draft
- On approval transition, current_version_id updates to latest version
"""
import hashlib
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models


logger = logging.getLogger("raas-core.versioning")


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content for conflict detection.

    Used for:
    - Detecting concurrent modifications (baseline hash comparison)
    - Verifying content integrity
    """
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def get_next_version_number(db: Session, requirement_id: UUID) -> int:
    """Get the next version number for a requirement.

    Returns 1 for new requirements, or max_version + 1 for existing.
    """
    max_version = db.query(func.max(models.RequirementVersion.version_number)).filter(
        models.RequirementVersion.requirement_id == requirement_id
    ).scalar() or 0
    return max_version + 1


def create_requirement_version(
    db: Session,
    requirement: models.Requirement,
    content: str,
    user_id: Optional[UUID] = None,
    source_work_item_id: Optional[UUID] = None,
    change_reason: Optional[str] = None,
) -> models.RequirementVersion:
    """Create a new immutable version snapshot of a requirement.

    This function:
    1. Computes content hash for conflict detection
    2. Determines next version number
    3. Creates RequirementVersion record
    4. Updates requirement's content_hash

    Does NOT update current_version_id - that happens on approval transition.

    Args:
        db: Database session
        requirement: The requirement being versioned
        content: The content to snapshot
        user_id: User making the change
        source_work_item_id: Work Item (CR/IR) that caused this version
        change_reason: Human-readable reason for the change

    Returns:
        The created RequirementVersion
    """
    content_hash = compute_content_hash(content)
    version_number = get_next_version_number(db, requirement.id)

    version = models.RequirementVersion(
        requirement_id=requirement.id,
        version_number=version_number,
        content=content,
        content_hash=content_hash,
        title=requirement.title,
        description=requirement.description,
        source_work_item_id=source_work_item_id,
        change_reason=change_reason,
        created_by_user_id=user_id,
    )

    db.add(version)
    db.flush()  # Get the version ID

    # Update requirement's content_hash for conflict detection
    requirement.content_hash = content_hash

    logger.info(
        f"Created version {version_number} for requirement "
        f"{requirement.human_readable_id or requirement.id}"
        f"{f' from work item {source_work_item_id}' if source_work_item_id else ''}"
    )

    return version


def get_latest_version(db: Session, requirement_id: UUID) -> Optional[models.RequirementVersion]:
    """Get the most recent version of a requirement.

    Returns None if no versions exist.
    """
    return db.query(models.RequirementVersion).filter(
        models.RequirementVersion.requirement_id == requirement_id
    ).order_by(
        models.RequirementVersion.version_number.desc()
    ).first()


def update_current_version_pointer(
    db: Session,
    requirement: models.Requirement,
) -> Optional[models.RequirementVersion]:
    """Update current_version_id to point to the latest version.

    Called when a requirement transitions to 'approved' status.

    Returns the version that was set as current, or None if no versions exist.
    """
    latest = get_latest_version(db, requirement.id)
    if latest:
        requirement.current_version_id = latest.id
        logger.info(
            f"Updated current_version_id for {requirement.human_readable_id or requirement.id} "
            f"to version {latest.version_number}"
        )
    return latest


def update_deployed_version_pointer(
    db: Session,
    requirement: models.Requirement,
    version_id: Optional[UUID] = None,
) -> Optional[models.RequirementVersion]:
    """Update deployed_version_id to track production deployment.

    Called when a Release deploys to production.

    Args:
        db: Database session
        requirement: The requirement being deployed
        version_id: Specific version to mark as deployed (defaults to current_version_id)

    Returns the version that was set as deployed, or None if no version found.
    """
    if version_id:
        version = db.query(models.RequirementVersion).filter(
            models.RequirementVersion.id == version_id
        ).first()
    elif requirement.current_version_id:
        version = db.query(models.RequirementVersion).filter(
            models.RequirementVersion.id == requirement.current_version_id
        ).first()
    else:
        version = get_latest_version(db, requirement.id)

    if version:
        requirement.deployed_version_id = version.id
        logger.info(
            f"Updated deployed_version_id for {requirement.human_readable_id or requirement.id} "
            f"to version {version.version_number}"
        )
    return version


def should_regress_to_draft(requirement: models.Requirement) -> bool:
    """Check if a requirement should regress to draft status.

    Requirements in 'approved' status regress to 'draft' when their content changes.
    This ensures specification changes go through the review workflow again.

    Note: Requirements in 'review' status also regress to draft on content change,
    as the reviewed content is no longer what's being submitted.
    """
    return requirement.status in [
        models.LifecycleStatus.APPROVED,
        models.LifecycleStatus.REVIEW,
    ]


def content_has_changed(old_content: Optional[str], new_content: str) -> bool:
    """Check if content has materially changed.

    Uses hash comparison for efficiency on large content.
    """
    if old_content is None:
        return True

    old_hash = compute_content_hash(old_content)
    new_hash = compute_content_hash(new_content)
    return old_hash != new_hash
