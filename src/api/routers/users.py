"""Users API endpoints (solo mode - no authentication)."""
import logging
from typing import Optional
from uuid import UUID
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from raas_core import crud, schemas

from ..database import get_db

logger = logging.getLogger("raas-core.users")

router = APIRouter(tags=["users"])


@router.get("/", response_model=schemas.UserListResponse)
def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    """
    List all users with pagination.

    Returns all active users in the system.
    """
    # Calculate skip
    skip = (page - 1) * page_size

    # List users
    users, total = crud.list_users(
        db=db,
        skip=skip,
        limit=page_size,
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
):
    """
    Search for users with optional filtering.

    - **organization_id**: Only return users who are members of this organization
    - **search**: Search term to match against email and full name (case-insensitive)
    """
    # Calculate skip
    skip = (page - 1) * page_size

    # Search users (no org membership verification in solo mode)
    users, total = crud.search_users(
        db=db,
        organization_id=organization_id,
        search=search,
        skip=skip,
        limit=page_size,
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
):
    """
    Get a user by ID.

    Returns basic user information if the user exists.
    """
    user = crud.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@router.get("/by-email/{email}", response_model=schemas.UserResponse)
def get_user_by_email(
    email: str,
    db: Session = Depends(get_db),
):
    """
    Get a user by email address.

    Useful for finding a user's UUID when you only know their email.
    Email matching is case-insensitive.
    """
    user = crud.get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user
