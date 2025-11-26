"""Users API endpoints with RBAC permission checks."""
import logging
from typing import Optional
from uuid import UUID
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from raas_core import crud, schemas, models

from ..database import get_db
from ..dependencies import get_current_user_optional

logger = logging.getLogger("raas-core.users")

router = APIRouter(tags=["users"])


@router.get("/", response_model=schemas.UserListResponse)
def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    List users with pagination.

    In team mode, returns only users who are in organizations the current user
    is also a member of (prevents full user enumeration).
    """
    # Calculate skip
    skip = (page - 1) * page_size

    # List users - filter by shared org membership in team mode
    users, total = crud.list_users(
        db=db,
        skip=skip,
        limit=page_size,
        requesting_user_id=current_user.id if current_user else None,
    )

    total_pages = ceil(total / page_size) if total > 0 else 0

    logger.debug(f"Listed {total} users (page {page}/{total_pages})")

    return schemas.UserListResponse(
        items=users,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/search", response_model=schemas.UserListResponse)
def search_users(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    organization_id: Optional[UUID] = Query(None, description="Filter by organization membership"),
    search: Optional[str] = Query(None, description="Search by email or name"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Search for users with optional filtering.

    In team mode, can only search users in organizations the current user is a member of.

    - **organization_id**: Only return users who are members of this organization
    - **search**: Search term to match against email and full name (case-insensitive)
    """
    # Calculate skip
    skip = (page - 1) * page_size

    # Search users - filter by shared org membership in team mode
    users, total = crud.search_users(
        db=db,
        organization_id=organization_id,
        search=search,
        skip=skip,
        limit=page_size,
        requesting_user_id=current_user.id if current_user else None,
    )

    total_pages = ceil(total / page_size) if total > 0 else 0

    logger.debug(f"User search: found {total} users (page {page}/{total_pages})")

    return schemas.UserListResponse(
        items=users,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/{user_id}", response_model=schemas.UserResponse)
def get_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Get a user by ID.

    In team mode, can only view users who share at least one organization with you.
    """
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # In team mode, verify users share at least one organization
    if current_user and current_user.id != user_id:
        if not crud.users_share_organization(db, current_user.id, user_id):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "permission_denied",
                    "message": "You can only view users who are members of organizations you belong to.",
                    "resource_type": "user",
                }
            )

    return user


@router.get("/by-email/{email}", response_model=schemas.UserResponse)
def get_user_by_email(
    email: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Get a user by email address.

    In team mode, can only view users who share at least one organization with you.
    Email matching is case-insensitive.
    """
    user = crud.get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # In team mode, verify users share at least one organization
    if current_user and current_user.id != user.id:
        if not crud.users_share_organization(db, current_user.id, user.id):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "permission_denied",
                    "message": "You can only view users who are members of organizations you belong to.",
                    "resource_type": "user",
                }
            )

    return user
