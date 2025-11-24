"""API dependencies for raas-core routers.

These dependencies work in both solo mode and team mode.
"""
from typing import Optional
from fastapi import Request

from raas_core.models import User


def get_current_user_optional(request: Request) -> Optional[User]:
    """
    Get current user from request state if available.

    In team mode with authentication, the AuthMiddleware stores the user in
    request.state.user. In solo mode, this returns None and CRUD functions
    skip permission checks.

    Args:
        request: FastAPI request

    Returns:
        User object if authenticated, None if solo mode
    """
    return getattr(request.state, "user", None)
