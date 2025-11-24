"""Permission checking for role-based access control.

This module implements permission validation for RAAS-FEAT-048.
It enforces organization and project roles to control what users can do.

Organization Roles:
- owner: Full control, can delete organization
- admin: Manage members and projects, cannot delete org
- member: View and participate in projects
- viewer: Read-only access

Project Roles:
- admin: Full control over project and requirements
- editor: Create and update requirements
- viewer: Read-only access
"""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger("raas-core.permissions")


class PermissionDeniedError(Exception):
    """Raised when a user lacks permission for an operation."""

    def __init__(
        self,
        message: str,
        required_role: Optional[str] = None,
        current_role: Optional[str] = None,
        resource_type: Optional[str] = None,
    ):
        self.message = message
        self.required_role = required_role
        self.current_role = current_role
        self.resource_type = resource_type
        super().__init__(message)


# Organization role hierarchy (higher number = more permissions)
ORG_ROLE_HIERARCHY = {
    models.MemberRole.VIEWER: 1,
    models.MemberRole.MEMBER: 2,
    models.MemberRole.ADMIN: 3,
    models.MemberRole.OWNER: 4,
}

# Project role hierarchy
PROJECT_ROLE_HIERARCHY = {
    models.ProjectRole.VIEWER: 1,
    models.ProjectRole.EDITOR: 2,
    models.ProjectRole.ADMIN: 3,
}


def get_user_org_role(
    db: Session,
    user_id: UUID,
    organization_id: UUID,
) -> Optional[models.MemberRole]:
    """Get user's role in an organization.

    Args:
        db: Database session
        user_id: User UUID
        organization_id: Organization UUID

    Returns:
        User's role in the organization, or None if not a member
    """
    membership = (
        db.query(models.OrganizationMember)
        .filter(
            models.OrganizationMember.user_id == user_id,
            models.OrganizationMember.organization_id == organization_id,
        )
        .first()
    )
    return membership.role if membership else None


def get_user_project_role(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> Optional[models.ProjectRole]:
    """Get user's role in a project.

    Args:
        db: Database session
        user_id: User UUID
        project_id: Project UUID

    Returns:
        User's role in the project, or None if not a member
    """
    membership = (
        db.query(models.ProjectMember)
        .filter(
            models.ProjectMember.user_id == user_id,
            models.ProjectMember.project_id == project_id,
        )
        .first()
    )
    return membership.role if membership else None


def check_org_permission(
    db: Session,
    user_id: UUID,
    organization_id: UUID,
    min_role: models.MemberRole,
    operation: str,
) -> None:
    """Check if user has minimum organization role for an operation.

    Args:
        db: Database session
        user_id: User UUID
        organization_id: Organization UUID
        min_role: Minimum required role
        operation: Description of operation for error message

    Raises:
        PermissionDeniedError: If user lacks required permission
    """
    user_role = get_user_org_role(db, user_id, organization_id)

    if not user_role:
        logger.warning(
            f"User {user_id} attempted {operation} on org {organization_id} but is not a member"
        )
        raise PermissionDeniedError(
            f"You must be a member of this organization to {operation}. "
            f"Contact an organization administrator to request access.",
            required_role=min_role.value,
            current_role=None,
            resource_type="organization",
        )

    if ORG_ROLE_HIERARCHY[user_role] < ORG_ROLE_HIERARCHY[min_role]:
        logger.warning(
            f"User {user_id} attempted {operation} on org {organization_id} "
            f"with role {user_role.value} but needs {min_role.value}"
        )
        raise PermissionDeniedError(
            f"You need {min_role.value} role to {operation}. "
            f"Your current role is {user_role.value}. "
            f"Contact an organization administrator to request elevated permissions.",
            required_role=min_role.value,
            current_role=user_role.value,
            resource_type="organization",
        )

    logger.debug(
        f"User {user_id} authorized for {operation} on org {organization_id} with role {user_role.value}"
    )


def check_project_permission(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    min_role: models.ProjectRole,
    operation: str,
) -> None:
    """Check if user has minimum project role for an operation.

    Also checks organization membership as a fallback.

    Args:
        db: Database session
        user_id: User UUID
        project_id: Project UUID
        min_role: Minimum required project role
        operation: Description of operation for error message

    Raises:
        PermissionDeniedError: If user lacks required permission
    """
    # Get project to check organization membership as fallback
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise PermissionDeniedError(
            f"Project not found",
            resource_type="project",
        )

    # Check project role first
    user_project_role = get_user_project_role(db, user_id, project_id)

    # If no project role, check if user is org admin/owner (has implicit access)
    if not user_project_role:
        user_org_role = get_user_org_role(db, user_id, project.organization_id)

        # Org admins and owners have implicit project admin access
        if user_org_role in [models.MemberRole.ADMIN, models.MemberRole.OWNER]:
            logger.debug(
                f"User {user_id} authorized for {operation} on project {project_id} "
                f"via org role {user_org_role.value}"
            )
            return

        # Not a project member and not an org admin
        logger.warning(
            f"User {user_id} attempted {operation} on project {project_id} but is not a member"
        )
        raise PermissionDeniedError(
            f"You must be a member of this project to {operation}. "
            f"Contact a project administrator to request access.",
            required_role=min_role.value,
            current_role=None,
            resource_type="project",
        )

    # Check if project role is sufficient
    if PROJECT_ROLE_HIERARCHY[user_project_role] < PROJECT_ROLE_HIERARCHY[min_role]:
        logger.warning(
            f"User {user_id} attempted {operation} on project {project_id} "
            f"with role {user_project_role.value} but needs {min_role.value}"
        )
        raise PermissionDeniedError(
            f"You need {min_role.value} role to {operation}. "
            f"Your current role is {user_project_role.value}. "
            f"Contact a project administrator to request elevated permissions.",
            required_role=min_role.value,
            current_role=user_project_role.value,
            resource_type="project",
        )

    logger.debug(
        f"User {user_id} authorized for {operation} on project {project_id} "
        f"with role {user_project_role.value}"
    )


def can_create_requirement(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> bool:
    """Check if user can create requirements in a project.

    Requires: Project editor role or higher, or org admin/owner.

    Args:
        db: Database session
        user_id: User UUID
        project_id: Project UUID

    Returns:
        True if user can create requirements

    Raises:
        PermissionDeniedError: If user lacks permission
    """
    try:
        check_project_permission(
            db, user_id, project_id, models.ProjectRole.EDITOR, "create requirements"
        )
        return True
    except PermissionDeniedError:
        raise


def can_update_requirement(
    db: Session,
    user_id: UUID,
    requirement_id: UUID,
) -> bool:
    """Check if user can update a requirement.

    Requires: Project editor role or higher in the requirement's project.

    Args:
        db: Database session
        user_id: User UUID
        requirement_id: Requirement UUID

    Returns:
        True if user can update the requirement

    Raises:
        PermissionDeniedError: If user lacks permission
    """
    requirement = (
        db.query(models.Requirement)
        .filter(models.Requirement.id == requirement_id)
        .first()
    )
    if not requirement:
        raise PermissionDeniedError("Requirement not found", resource_type="requirement")

    try:
        check_project_permission(
            db,
            user_id,
            requirement.project_id,
            models.ProjectRole.EDITOR,
            "update requirements",
        )
        return True
    except PermissionDeniedError:
        raise


def can_delete_requirement(
    db: Session,
    user_id: UUID,
    requirement_id: UUID,
) -> bool:
    """Check if user can delete a requirement.

    Requires: Project admin role or org admin/owner.

    Args:
        db: Database session
        user_id: User UUID
        requirement_id: Requirement UUID

    Returns:
        True if user can delete the requirement

    Raises:
        PermissionDeniedError: If user lacks permission
    """
    requirement = (
        db.query(models.Requirement)
        .filter(models.Requirement.id == requirement_id)
        .first()
    )
    if not requirement:
        raise PermissionDeniedError("Requirement not found", resource_type="requirement")

    try:
        check_project_permission(
            db,
            user_id,
            requirement.project_id,
            models.ProjectRole.ADMIN,
            "delete requirements",
        )
        return True
    except PermissionDeniedError:
        raise


def can_manage_organization(
    db: Session,
    user_id: UUID,
    organization_id: UUID,
) -> bool:
    """Check if user can manage organization settings.

    Requires: Organization admin or owner role.

    Args:
        db: Database session
        user_id: User UUID
        organization_id: Organization UUID

    Returns:
        True if user can manage the organization

    Raises:
        PermissionDeniedError: If user lacks permission
    """
    try:
        check_org_permission(
            db,
            user_id,
            organization_id,
            models.MemberRole.ADMIN,
            "manage organization settings",
        )
        return True
    except PermissionDeniedError:
        raise


def can_delete_organization(
    db: Session,
    user_id: UUID,
    organization_id: UUID,
) -> bool:
    """Check if user can delete an organization.

    Requires: Organization owner role.

    Args:
        db: Database session
        user_id: User UUID
        organization_id: Organization UUID

    Returns:
        True if user can delete the organization

    Raises:
        PermissionDeniedError: If user lacks permission
    """
    try:
        check_org_permission(
            db,
            user_id,
            organization_id,
            models.MemberRole.OWNER,
            "delete organization",
        )
        return True
    except PermissionDeniedError:
        raise


def can_manage_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> bool:
    """Check if user can manage project settings.

    Requires: Project admin role or org admin/owner.

    Args:
        db: Database session
        user_id: User UUID
        project_id: Project UUID

    Returns:
        True if user can manage the project

    Raises:
        PermissionDeniedError: If user lacks permission
    """
    try:
        check_project_permission(
            db, user_id, project_id, models.ProjectRole.ADMIN, "manage project settings"
        )
        return True
    except PermissionDeniedError:
        raise


def can_delete_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> bool:
    """Check if user can delete a project.

    Requires: Project admin role or org admin/owner.

    Args:
        db: Database session
        user_id: User UUID
        project_id: Project UUID

    Returns:
        True if user can delete the project

    Raises:
        PermissionDeniedError: If user lacks permission
    """
    try:
        check_project_permission(
            db, user_id, project_id, models.ProjectRole.ADMIN, "delete project"
        )
        return True
    except PermissionDeniedError:
        raise
