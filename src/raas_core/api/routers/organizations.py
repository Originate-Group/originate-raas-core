"""Organizations API endpoints with RBAC permission checks."""
import logging
from typing import Optional
from uuid import UUID
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from raas_core import crud, schemas, models
from raas_core.permissions import (
    check_org_permission,
    PermissionDeniedError,
    get_user_org_role,
)

from ..database import get_db
from ..dependencies import get_current_user_optional

logger = logging.getLogger("raas-core.organizations")


def _handle_permission_error(e: PermissionDeniedError) -> HTTPException:
    """Convert PermissionDeniedError to HTTPException with proper 403 response."""
    return HTTPException(
        status_code=403,
        detail={
            "error": "permission_denied",
            "message": e.message,
            "required_role": e.required_role,
            "current_role": e.current_role,
            "resource_type": e.resource_type,
        }
    )

router = APIRouter(tags=["organizations"])


@router.post("/", response_model=schemas.OrganizationResponse, status_code=201)
def create_organization(
    organization: schemas.OrganizationCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Create a new organization.

    Any authenticated user can create an organization. The creator becomes the owner.

    - **name**: Organization name
    - **slug**: URL-friendly slug (lowercase, alphanumeric, hyphens)
    - **settings**: Optional JSON settings
    """
    # Check if slug already exists
    existing = crud.get_organization_by_slug(db, organization.slug)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Organization with slug '{organization.slug}' already exists"
        )

    try:
        result = crud.create_organization(
            db=db,
            name=organization.name,
            slug=organization.slug,
            settings=organization.settings,
        )
        logger.info(f"Created organization '{result.name}' (ID: {result.id})")

        # In team mode, make the creating user the owner
        if current_user:
            crud.add_organization_member(
                db=db,
                organization_id=result.id,
                user_id=current_user.id,
                role=models.MemberRole.OWNER,
            )
            logger.info(f"Added user {current_user.email} as owner of organization {result.id}")

        return result
    except Exception as e:
        logger.error(f"Error creating organization: {e}", exc_info=True)
        raise


@router.get("/", response_model=schemas.OrganizationListResponse)
def list_organizations(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    List organizations with pagination.

    In team mode, returns only organizations where the user is a member.
    In solo mode, returns all organizations.
    """
    # Calculate skip
    skip = (page - 1) * page_size

    # Get organizations filtered by user membership in team mode
    organizations, total = crud.get_organizations(
        db=db,
        skip=skip,
        limit=page_size,
        user_id=current_user.id if current_user else None,
    )

    return schemas.OrganizationListResponse(
        items=organizations,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total > 0 else 0,
    )


@router.get("/{organization_id}", response_model=schemas.OrganizationResponse)
def get_organization(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Get a specific organization by ID.

    Requires membership in the organization (any role).
    """
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    # In team mode, verify user is a member of this organization
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, organization_id,
                models.MemberRole.VIEWER, "view organization"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    return organization


@router.put("/{organization_id}", response_model=schemas.OrganizationResponse)
def update_organization(
    organization_id: UUID,
    organization_update: schemas.OrganizationUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Update an organization.

    Requires Admin or Owner role in the organization.

    - **name**: New organization name (optional)
    - **settings**: New settings (optional)
    """
    # Check organization exists
    existing = crud.get_organization(db, organization_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Organization not found")

    # In team mode, verify user has admin or owner role
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, organization_id,
                models.MemberRole.ADMIN, "update organization settings"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    try:
        organization = crud.update_organization(
            db,
            organization_id,
            name=organization_update.name,
            settings=organization_update.settings,
        )
        return organization
    except Exception as e:
        logger.error(f"Error updating organization {organization_id}: {e}", exc_info=True)
        raise


@router.delete("/{organization_id}", status_code=204)
def delete_organization(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Delete an organization and all its data (cascading delete).

    Requires Owner role in the organization.

    Use with caution! This will delete all projects, requirements, and members.
    """
    # Check organization exists
    existing = crud.get_organization(db, organization_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Organization not found")

    # In team mode, verify user is the owner
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, organization_id,
                models.MemberRole.OWNER, "delete organization"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    success = crud.delete_organization(db, organization_id)
    if not success:
        raise HTTPException(status_code=404, detail="Organization not found")


# Organization Members endpoints

@router.get("/{organization_id}/members", response_model=list[schemas.OrganizationMemberResponse])
def list_organization_members(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    List all members of an organization.

    Requires membership in the organization (any role).
    """
    # Check organization exists
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    # In team mode, verify user is a member
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, organization_id,
                models.MemberRole.VIEWER, "view organization members"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    return crud.get_organization_members(db, organization_id)


@router.post("/{organization_id}/members", response_model=schemas.OrganizationMemberResponse, status_code=201)
def add_organization_member(
    organization_id: UUID,
    member: schemas.OrganizationMemberCreate,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Add a user to an organization.

    Requires Admin or Owner role. Only Owners can add other Owners.

    - **user_id**: UUID of the user to add
    - **role**: Organization role (owner, admin, member, viewer)
    """
    # Check organization exists
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    # In team mode, verify user has admin or owner role
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, organization_id,
                models.MemberRole.ADMIN, "add organization members"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

        # Only owners can add other owners
        if member.role == models.MemberRole.OWNER:
            user_role = get_user_org_role(db, current_user.id, organization_id)
            if user_role != models.MemberRole.OWNER:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "permission_denied",
                        "message": "Only organization owners can add other owners.",
                        "required_role": "owner",
                        "current_role": user_role.value if user_role else None,
                        "resource_type": "organization",
                    }
                )

    try:
        result = crud.add_organization_member(
            db=db,
            organization_id=organization_id,
            user_id=member.user_id,
            role=member.role,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{organization_id}/members/{user_id}", response_model=schemas.OrganizationMemberResponse)
def update_organization_member(
    organization_id: UUID,
    user_id: UUID,
    member_update: schemas.OrganizationMemberUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Update an organization member's role.

    Requires Admin or Owner role. Only Owners can promote to Owner.

    - **role**: New organization role
    """
    # Check organization exists
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    # In team mode, verify user has admin or owner role
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, organization_id,
                models.MemberRole.ADMIN, "update organization member roles"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

        # Only owners can promote to owner
        if member_update.role == models.MemberRole.OWNER:
            user_role = get_user_org_role(db, current_user.id, organization_id)
            if user_role != models.MemberRole.OWNER:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "permission_denied",
                        "message": "Only organization owners can promote members to owner.",
                        "required_role": "owner",
                        "current_role": user_role.value if user_role else None,
                        "resource_type": "organization",
                    }
                )

    try:
        result = crud.update_organization_member_role(
            db=db,
            organization_id=organization_id,
            user_id=user_id,
            role=member_update.role,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{organization_id}/members/{user_id}", status_code=204)
def remove_organization_member(
    organization_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Remove a user from an organization.

    Requires Admin or Owner role. Owners can only be removed by other Owners.
    """
    # Check organization exists
    organization = crud.get_organization(db, organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")

    # In team mode, verify user has admin or owner role
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, organization_id,
                models.MemberRole.ADMIN, "remove organization members"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

        # Check if target user is an owner - only owners can remove owners
        target_role = get_user_org_role(db, user_id, organization_id)
        if target_role == models.MemberRole.OWNER:
            user_role = get_user_org_role(db, current_user.id, organization_id)
            if user_role != models.MemberRole.OWNER:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "permission_denied",
                        "message": "Only organization owners can remove other owners.",
                        "required_role": "owner",
                        "current_role": user_role.value if user_role else None,
                        "resource_type": "organization",
                    }
                )

    success = crud.remove_organization_member(
        db=db,
        organization_id=organization_id,
        user_id=user_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")
