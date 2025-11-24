"""Hierarchy validation for requirements.

Enforces the Epic > Component > Feature > Requirement hierarchy.
"""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger("raas-core.hierarchy_validation")


# Canonical mapping of valid parent-child type relationships
VALID_PARENT_TYPES = {
    models.RequirementType.EPIC: None,  # Epics have no parent (top-level)
    models.RequirementType.COMPONENT: models.RequirementType.EPIC,
    models.RequirementType.FEATURE: models.RequirementType.COMPONENT,
    models.RequirementType.REQUIREMENT: models.RequirementType.FEATURE,
}


class HierarchyValidationError(Exception):
    """Raised when hierarchy validation fails."""

    def __init__(
        self,
        message: str,
        child_type: models.RequirementType,
        expected_parent_type: Optional[models.RequirementType],
        actual_parent_type: Optional[models.RequirementType] = None,
        parent_id: Optional[UUID] = None,
        parent_title: Optional[str] = None,
    ):
        self.message = message
        self.child_type = child_type
        self.expected_parent_type = expected_parent_type
        self.actual_parent_type = actual_parent_type
        self.parent_id = parent_id
        self.parent_title = parent_title
        super().__init__(message)


def validate_parent_type(
    db: Session,
    child_type: models.RequirementType,
    parent_id: Optional[UUID],
) -> None:
    """Validate that the parent-child type relationship is valid.

    Args:
        db: Database session
        child_type: The type of requirement being created/updated
        parent_id: The parent requirement ID (None for epics)

    Raises:
        HierarchyValidationError: If the parent type is invalid for the child type
        ValueError: If parent_id is not found (404 case)
    """
    expected_parent_type = VALID_PARENT_TYPES[child_type]

    # Case 1: Epic requirements (top-level only)
    if child_type == models.RequirementType.EPIC:
        if parent_id is not None:
            logger.warning(f"Attempted to create epic with parent_id={parent_id}")
            raise HierarchyValidationError(
                message=f"Cannot create epic with a parent. Epics are top-level requirements and must not have a parent_id.",
                child_type=child_type,
                expected_parent_type=None,
                parent_id=parent_id,
            )
        # Epic without parent is valid
        return

    # Case 2: Non-epic requirements (must have parent)
    if parent_id is None:
        logger.warning(f"Attempted to create {child_type.value} without parent_id")
        raise HierarchyValidationError(
            message=f"Cannot create {child_type.value} without a parent. "
                    f"{child_type.value.capitalize()}s must have a {expected_parent_type.value} as their parent.",
            child_type=child_type,
            expected_parent_type=expected_parent_type,
        )

    # Case 3: Validate parent exists and has correct type
    parent = db.query(models.Requirement).filter(models.Requirement.id == parent_id).first()

    if not parent:
        # Parent doesn't exist - this is a 404 case, not a validation error
        logger.warning(f"Parent requirement {parent_id} not found")
        raise ValueError(f"Parent requirement {parent_id} not found.")

    # Check parent type matches expected type
    if parent.type != expected_parent_type:
        logger.warning(
            f"Invalid parent type for {child_type.value}: "
            f"parent {parent_id} is {parent.type.value}, expected {expected_parent_type.value}"
        )
        raise HierarchyValidationError(
            message=f"Cannot create {child_type.value} as child of {parent.type.value}. "
                    f"{child_type.value.capitalize()}s must have a {expected_parent_type.value} as their parent. "
                    f"Parent '{parent.title}' ({parent_id}) is a {parent.type.value}.",
            child_type=child_type,
            expected_parent_type=expected_parent_type,
            actual_parent_type=parent.type,
            parent_id=parent_id,
            parent_title=parent.title,
        )

    # Validation passed
    logger.debug(f"Hierarchy validation passed: {child_type.value} -> {parent.type.value} parent")


def find_hierarchy_violations(
    db: Session,
    project_id: Optional[UUID] = None,
) -> list[dict]:
    """Find all requirements that violate hierarchy rules.

    Args:
        db: Database session
        project_id: Optional project ID filter

    Returns:
        List of violation dictionaries with details for remediation
    """
    violations = []

    # Query all requirements (optionally filtered by project)
    query = db.query(models.Requirement)
    if project_id:
        query = query.filter(models.Requirement.project_id == project_id)

    requirements = query.all()

    for req in requirements:
        try:
            # Validate each requirement against hierarchy rules
            validate_parent_type(db, req.type, req.parent_id)
        except HierarchyValidationError as e:
            # Found a violation
            violation = {
                "requirement_id": str(req.id),
                "requirement_human_id": req.human_readable_id,
                "requirement_title": req.title,
                "requirement_type": req.type.value,
                "parent_id": str(req.parent_id) if req.parent_id else None,
                "parent_human_id": e.parent_title if e.parent_title else None,
                "parent_title": e.parent_title,
                "parent_type": e.actual_parent_type.value if e.actual_parent_type else None,
                "expected_parent_type": e.expected_parent_type.value if e.expected_parent_type else None,
                "violation": e.message,
            }
            violations.append(violation)
            logger.debug(f"Found hierarchy violation: {req.human_readable_id} - {e.message}")
        except ValueError:
            # Parent not found - different kind of data integrity issue
            violation = {
                "requirement_id": str(req.id),
                "requirement_human_id": req.human_readable_id,
                "requirement_title": req.title,
                "requirement_type": req.type.value,
                "parent_id": str(req.parent_id) if req.parent_id else None,
                "parent_human_id": None,
                "parent_title": None,
                "parent_type": None,
                "expected_parent_type": VALID_PARENT_TYPES[req.type].value if VALID_PARENT_TYPES[req.type] else None,
                "violation": f"Parent requirement {req.parent_id} not found (orphaned requirement)",
            }
            violations.append(violation)
            logger.debug(f"Found orphaned requirement: {req.human_readable_id}")

    logger.info(f"Found {len(violations)} hierarchy violations")
    return violations
