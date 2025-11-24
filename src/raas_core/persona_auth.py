"""Persona-based authorization for requirement lifecycle transitions.

Enforces an authorization matrix that validates declared persona against
allowed transitions per requirement type. This prevents AI agents from
bypassing role restrictions regardless of how "helpful" they try to be.

The system uses a default matrix that can be overridden per organization
via the organization's settings JSON field.
"""
import enum
import logging
from typing import Optional

from .models import LifecycleStatus, RequirementType

logger = logging.getLogger("raas-core.persona_auth")


class Persona(str, enum.Enum):
    """Workflow personas that can perform requirement transitions.

    These represent functional roles in the development workflow,
    not user account roles. An agent or user declares their persona
    when making transition requests.
    """
    ENTERPRISE_ARCHITECT = "enterprise_architect"
    PRODUCT_OWNER = "product_owner"
    SCRUM_MASTER = "scrum_master"
    DEVELOPER = "developer"
    TESTER = "tester"
    RELEASE_MANAGER = "release_manager"


class PersonaAuthorizationError(Exception):
    """Raised when a persona is not authorized for a transition."""

    def __init__(
        self,
        message: str,
        persona: Persona,
        from_status: LifecycleStatus,
        to_status: LifecycleStatus,
        authorized_personas: list[Persona],
    ):
        super().__init__(message)
        self.persona = persona
        self.from_status = from_status
        self.to_status = to_status
        self.authorized_personas = authorized_personas


# Default transition authorization matrix
# Maps (from_status, to_status) -> set of authorized personas
# This matrix is used unless overridden in organization settings
DEFAULT_TRANSITION_MATRIX: dict[tuple[LifecycleStatus, LifecycleStatus], set[Persona]] = {
    # draft -> review: Anyone working on requirements can submit for review
    (LifecycleStatus.DRAFT, LifecycleStatus.REVIEW): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.PRODUCT_OWNER,
        Persona.SCRUM_MASTER,
        Persona.DEVELOPER,
    },

    # review -> approved: Only PO and EA can approve requirements
    (LifecycleStatus.REVIEW, LifecycleStatus.APPROVED): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.PRODUCT_OWNER,
    },

    # review -> draft: Send back for rework (most roles)
    (LifecycleStatus.REVIEW, LifecycleStatus.DRAFT): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.PRODUCT_OWNER,
        Persona.SCRUM_MASTER,
        Persona.DEVELOPER,
        Persona.TESTER,
    },

    # approved -> in_progress: Start implementation
    (LifecycleStatus.APPROVED, LifecycleStatus.IN_PROGRESS): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.PRODUCT_OWNER,
        Persona.SCRUM_MASTER,
        Persona.DEVELOPER,
    },

    # approved -> draft: Reopen for major changes
    (LifecycleStatus.APPROVED, LifecycleStatus.DRAFT): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.PRODUCT_OWNER,
    },

    # in_progress -> implemented: Developer marks work complete
    (LifecycleStatus.IN_PROGRESS, LifecycleStatus.IMPLEMENTED): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.DEVELOPER,
    },

    # in_progress -> approved: Back to backlog (blocked, deprioritized)
    (LifecycleStatus.IN_PROGRESS, LifecycleStatus.APPROVED): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.PRODUCT_OWNER,
        Persona.SCRUM_MASTER,
        Persona.DEVELOPER,
    },

    # implemented -> validated: ONLY testers can validate (no self-validation)
    (LifecycleStatus.IMPLEMENTED, LifecycleStatus.VALIDATED): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.TESTER,
    },

    # implemented -> in_progress: Rework needed (found issues)
    (LifecycleStatus.IMPLEMENTED, LifecycleStatus.IN_PROGRESS): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.DEVELOPER,
        Persona.TESTER,
    },

    # validated -> deployed: ONLY release manager can deploy
    (LifecycleStatus.VALIDATED, LifecycleStatus.DEPLOYED): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.RELEASE_MANAGER,
    },

    # validated -> implemented: Validation failed, needs fix
    (LifecycleStatus.VALIDATED, LifecycleStatus.IMPLEMENTED): {
        Persona.ENTERPRISE_ARCHITECT,
        Persona.TESTER,
    },
}


def get_transition_matrix(
    org_settings: Optional[dict] = None
) -> dict[tuple[LifecycleStatus, LifecycleStatus], set[Persona]]:
    """Get the transition authorization matrix, with optional org override.

    Args:
        org_settings: Organization settings dict that may contain
                     'persona_matrix' override configuration

    Returns:
        Transition matrix mapping (from, to) -> set of authorized personas
    """
    if org_settings and "persona_matrix" in org_settings:
        # Parse org-specific matrix from settings
        # Format: {"draft->review": ["developer", "product_owner"], ...}
        custom_matrix = org_settings["persona_matrix"]
        matrix = {}

        for transition_key, persona_list in custom_matrix.items():
            try:
                from_str, to_str = transition_key.split("->")
                from_status = LifecycleStatus(from_str.strip())
                to_status = LifecycleStatus(to_str.strip())
                personas = {Persona(p.strip()) for p in persona_list}
                matrix[(from_status, to_status)] = personas
            except (ValueError, KeyError) as e:
                logger.warning(f"Invalid persona_matrix entry '{transition_key}': {e}")
                continue

        # Merge with defaults (custom overrides default for same transition)
        merged = DEFAULT_TRANSITION_MATRIX.copy()
        merged.update(matrix)
        return merged

    return DEFAULT_TRANSITION_MATRIX


def get_authorized_personas(
    from_status: LifecycleStatus,
    to_status: LifecycleStatus,
    org_settings: Optional[dict] = None,
) -> set[Persona]:
    """Get the set of personas authorized for a specific transition.

    Args:
        from_status: Current lifecycle status
        to_status: Target lifecycle status
        org_settings: Optional organization settings for matrix override

    Returns:
        Set of personas authorized for this transition (empty if none)
    """
    matrix = get_transition_matrix(org_settings)
    return matrix.get((from_status, to_status), set())


def is_persona_authorized(
    persona: Persona,
    from_status: LifecycleStatus,
    to_status: LifecycleStatus,
    org_settings: Optional[dict] = None,
) -> bool:
    """Check if a persona is authorized for a specific transition.

    Args:
        persona: The declared persona attempting the transition
        from_status: Current lifecycle status
        to_status: Target lifecycle status
        org_settings: Optional organization settings for matrix override

    Returns:
        True if authorized, False otherwise
    """
    # No-op transitions (same status) are always allowed
    if from_status == to_status:
        return True

    authorized = get_authorized_personas(from_status, to_status, org_settings)
    return persona in authorized


def validate_persona_authorization(
    persona: Optional[Persona],
    from_status: LifecycleStatus,
    to_status: LifecycleStatus,
    org_settings: Optional[dict] = None,
    require_persona: bool = True,
) -> None:
    """Validate persona authorization and raise exception if not authorized.

    Args:
        persona: The declared persona (None if not provided)
        from_status: Current lifecycle status
        to_status: Target lifecycle status
        org_settings: Optional organization settings for matrix override
        require_persona: If True, missing persona raises error. If False,
                        missing persona skips authorization check.

    Raises:
        PersonaAuthorizationError: If persona is not authorized or missing
    """
    # No-op transitions are always allowed
    if from_status == to_status:
        return

    authorized_personas = get_authorized_personas(from_status, to_status, org_settings)

    # Handle missing persona
    if persona is None:
        if require_persona and authorized_personas:
            error_msg = (
                f"Persona declaration required for transition {from_status.value} -> {to_status.value}. "
                f"Authorized personas: {', '.join(p.value for p in authorized_personas)}."
            )
            logger.warning(f"Missing persona: {error_msg}")
            raise PersonaAuthorizationError(
                message=error_msg,
                persona=None,  # type: ignore
                from_status=from_status,
                to_status=to_status,
                authorized_personas=list(authorized_personas),
            )
        # If not requiring persona, allow the transition
        return

    # Check authorization
    if not is_persona_authorized(persona, from_status, to_status, org_settings):
        error_msg = (
            f"Persona '{persona.value}' is not authorized for transition "
            f"{from_status.value} -> {to_status.value}. "
            f"Authorized personas: {', '.join(p.value for p in authorized_personas)}."
        )
        logger.warning(f"Unauthorized transition: {error_msg}")
        raise PersonaAuthorizationError(
            message=error_msg,
            persona=persona,
            from_status=from_status,
            to_status=to_status,
            authorized_personas=list(authorized_personas),
        )

    logger.debug(
        f"Authorized: persona={persona.value}, "
        f"transition={from_status.value}->{to_status.value}"
    )
