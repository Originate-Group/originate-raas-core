"""API endpoints for guardrail management with RBAC permission checks."""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.orm import Session
from math import ceil

from tarka_core import crud, schemas, models
from tarka_core.permissions import (
    check_org_permission,
    PermissionDeniedError,
)

from ..database import get_db
from ..dependencies import get_current_user_optional

logger = logging.getLogger("raas-core.guardrails")


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


router = APIRouter(tags=["guardrails"])


@router.get("/template", response_model=schemas.GuardrailTemplateResponse)
async def get_guardrail_template():
    """
    Get the markdown template for creating a new guardrail.

    Returns a complete template with YAML frontmatter structure and
    inline guidance for filling in guardrail content.
    """
    template = crud.get_guardrail_template()
    return schemas.GuardrailTemplateResponse(template=template)


@router.post("/", response_model=schemas.GuardrailResponse, status_code=status.HTTP_201_CREATED)
async def create_guardrail(
    guardrail: schemas.GuardrailCreate,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Create a new guardrail with structured markdown content.

    Requires Admin or Owner role in the organization.

    The content field must contain properly formatted markdown with
    YAML frontmatter. Use GET /guardrails/template to obtain the template.

    Guardrails are organization-scoped and codify standards that guide
    requirement authoring across all projects.
    """
    # In team mode, verify user has admin or owner role in the organization
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, guardrail.organization_id,
                models.MemberRole.ADMIN, "create guardrails"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    try:
        db_guardrail = crud.create_guardrail(
            db=db,
            organization_id=guardrail.organization_id,
            content=guardrail.content,
            user_id=current_user.id if current_user else None,
        )
        logger.info(f"Created guardrail {db_guardrail.human_readable_id}")
        return db_guardrail
    except ValueError as e:
        logger.warning(f"Invalid guardrail content: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/{guardrail_id}", response_model=schemas.GuardrailResponse)
async def get_guardrail(
    guardrail_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Get a guardrail by UUID or human-readable ID.

    Requires membership in the guardrail's organization.

    Supports both UUID (e.g., 'a1b2c3d4-...') and human-readable ID
    (e.g., 'GUARD-SEC-001', case-insensitive).

    Returns the complete guardrail including full markdown content.
    """
    guardrail = crud.get_guardrail(db, guardrail_id)
    if not guardrail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guardrail not found: {guardrail_id}",
        )

    # In team mode, verify user is a member of the organization
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, guardrail.organization_id,
                models.MemberRole.VIEWER, "view guardrail"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    return guardrail


@router.patch("/{guardrail_id}", response_model=schemas.GuardrailResponse)
async def update_guardrail(
    guardrail_id: str,
    guardrail_update: schemas.GuardrailUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Update a guardrail with new markdown content.

    Requires Admin or Owner role in the organization.

    The content field must contain properly formatted markdown with
    YAML frontmatter. All fields in the frontmatter can be updated.
    """
    # Verify guardrail exists
    existing = crud.get_guardrail(db, guardrail_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guardrail not found: {guardrail_id}",
        )

    # In team mode, verify user has admin or owner role in the organization
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, existing.organization_id,
                models.MemberRole.ADMIN, "update guardrails"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    try:
        updated_guardrail = crud.update_guardrail(
            db=db,
            guardrail_id=str(existing.id),
            content=guardrail_update.content,
            user_id=current_user.id if current_user else None,
        )
        logger.info(f"Updated guardrail {updated_guardrail.human_readable_id}")
        return updated_guardrail
    except ValueError as e:
        logger.warning(f"Invalid guardrail content: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{guardrail_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_guardrail(
    guardrail_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    Delete a guardrail by UUID or human-readable ID.

    Requires Admin or Owner role in the organization.

    Supports both UUID (e.g., 'a1b2c3d4-...') and human-readable ID
    (e.g., 'GUARD-SEC-001', case-insensitive).

    Returns 204 No Content on success, 404 if not found.
    """
    # Verify guardrail exists first to get organization_id for permission check
    existing = crud.get_guardrail(db, guardrail_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guardrail not found: {guardrail_id}",
        )

    # In team mode, verify user has admin or owner role in the organization
    if current_user:
        try:
            check_org_permission(
                db, current_user.id, existing.organization_id,
                models.MemberRole.ADMIN, "delete guardrails"
            )
        except PermissionDeniedError as e:
            raise _handle_permission_error(e)

    success = crud.delete_guardrail(db, guardrail_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guardrail not found: {guardrail_id}",
        )
    logger.info(f"Deleted guardrail {guardrail_id}")


@router.get("/", response_model=schemas.GuardrailListResponse)
async def list_guardrails(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    organization_id: Optional[UUID] = Query(None, description="Filter by organization"),
    category: Optional[str] = Query(None, description="Filter by category (security, architecture, business)"),
    enforcement_level: Optional[str] = Query(None, description="Filter by enforcement level"),
    applies_to: Optional[str] = Query(None, description="Filter by requirement type applicability"),
    status: Optional[str] = Query("active", description="Filter by status (active, draft, deprecated, all)"),
    search: Optional[str] = Query(None, description="Search in title and content"),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """
    List and filter guardrails with pagination.

    In team mode, returns only guardrails from organizations where the user is a member.

    By default, returns only active guardrails. Use status='all' to see all.

    - **organization_id**: Filter by organization UUID
    - **category**: Filter by category (security, architecture, business)
    - **enforcement_level**: Filter by level (advisory, recommended, mandatory)
    - **applies_to**: Filter by requirement type (epic, component, feature, requirement)
    - **status**: Filter by status (defaults to 'active')
    - **search**: Search keyword in title/content
    """
    skip = (page - 1) * page_size

    # Handle 'all' status filter - pass None to show all statuses
    status_filter = None if status == "all" else status

    guardrails, total = crud.list_guardrails(
        db=db,
        skip=skip,
        limit=page_size,
        organization_id=organization_id,
        category=category,
        enforcement_level=enforcement_level,
        applies_to=applies_to,
        status=status_filter,
        search=search,
        user_id=current_user.id if current_user else None,
    )

    total_pages = ceil(total / page_size) if total > 0 else 0

    return schemas.GuardrailListResponse(
        items=guardrails,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
