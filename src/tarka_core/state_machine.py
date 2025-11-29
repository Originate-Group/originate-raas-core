"""State machine validation for requirement lifecycle status transitions.

CR-004 Phase 4 (RAAS-COMP-047): Simplified to 4-state model.
Requirements are SPECIFICATIONS - implementation status belongs on Work Items.

Valid states: draft → review → approved → deprecated
- draft: Initial state, not yet ready for review
- review: Submitted for stakeholder review
- approved: Approved specification, ready for implementation
- deprecated: Terminal state for soft retirement

Implementation lifecycle (in_progress, implemented, validated, deployed)
is now tracked on Work Items, not Requirements.
"""
import logging
from typing import Optional

from .models import LifecycleStatus

logger = logging.getLogger("raas-core.state_machine")


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        message: str,
        current_status: LifecycleStatus,
        requested_status: LifecycleStatus,
        allowed_transitions: list[LifecycleStatus]
    ):
        super().__init__(message)
        self.current_status = current_status
        self.requested_status = requested_status
        self.allowed_transitions = allowed_transitions


# State machine transition matrix (CR-004 Phase 4: 4-state model)
# Maps current status → list of allowed next statuses
TRANSITION_MATRIX: dict[LifecycleStatus, list[LifecycleStatus]] = {
    LifecycleStatus.DRAFT: [
        LifecycleStatus.DRAFT,      # No-op (allowed)
        LifecycleStatus.REVIEW,     # Forward: submit for review
    ],
    LifecycleStatus.REVIEW: [
        LifecycleStatus.REVIEW,     # No-op (allowed)
        LifecycleStatus.DRAFT,      # Back: needs more work
        LifecycleStatus.APPROVED,   # Forward: approved after review
        LifecycleStatus.DEPRECATED, # Terminal: soft retirement (RAAS-FEAT-080)
    ],
    LifecycleStatus.APPROVED: [
        LifecycleStatus.APPROVED,   # No-op (allowed)
        LifecycleStatus.DRAFT,      # Back: reopen for major changes
        LifecycleStatus.REVIEW,     # Back: needs re-review after changes
        LifecycleStatus.DEPRECATED, # Terminal: soft retirement (RAAS-FEAT-080)
    ],
    LifecycleStatus.DEPRECATED: [
        LifecycleStatus.DEPRECATED, # No-op (allowed)
        # Note: DEPRECATED is terminal - cannot transition out (RAAS-FEAT-080)
        # Use deprecated for soft retirement instead of hard deletion
        # Deprecated requirements are excluded from default queries
    ],
}


def is_transition_valid(
    current_status: LifecycleStatus,
    new_status: LifecycleStatus
) -> bool:
    """
    Check if a status transition is valid.

    Args:
        current_status: Current lifecycle status
        new_status: Requested new lifecycle status

    Returns:
        True if transition is allowed, False otherwise
    """
    allowed_transitions = TRANSITION_MATRIX.get(current_status, [])
    return new_status in allowed_transitions


def validate_transition(
    current_status: LifecycleStatus,
    new_status: LifecycleStatus
) -> None:
    """
    Validate a status transition and raise exception if invalid.

    Args:
        current_status: Current lifecycle status
        new_status: Requested new lifecycle status

    Raises:
        StateTransitionError: If the transition is not allowed
    """
    # No-op transitions are always allowed (setting same status)
    if current_status == new_status:
        logger.debug(f"No-op transition: {current_status.value} → {new_status.value}")
        return

    if not is_transition_valid(current_status, new_status):
        allowed_transitions = TRANSITION_MATRIX.get(current_status, [])
        allowed_names = [s.value for s in allowed_transitions if s != current_status]

        error_msg = (
            f"Invalid status transition: {current_status.value} → {new_status.value}. "
            f"From {current_status.value}, you can only transition to: {', '.join(allowed_names)}."
        )

        # Add helpful guidance based on the attempted transition
        if current_status == LifecycleStatus.DRAFT and new_status == LifecycleStatus.APPROVED:
            error_msg += " Requirements must be reviewed before approval. Transition to 'review' first."
        elif current_status == LifecycleStatus.DRAFT and new_status == LifecycleStatus.DEPRECATED:
            error_msg += " Draft requirements cannot be deprecated. Submit for review first, or delete if unwanted."
        elif current_status == LifecycleStatus.DEPRECATED:
            error_msg += " Deprecated requirements are terminal and cannot be reactivated. Create a new requirement instead."

        logger.warning(f"Blocked transition: {error_msg}")
        raise StateTransitionError(
            message=error_msg,
            current_status=current_status,
            requested_status=new_status,
            allowed_transitions=allowed_transitions
        )

    logger.debug(f"Valid transition: {current_status.value} → {new_status.value}")


def get_allowed_transitions(current_status: LifecycleStatus) -> list[LifecycleStatus]:
    """
    Get list of allowed transitions from current status.

    Args:
        current_status: Current lifecycle status

    Returns:
        List of allowed next statuses (excluding no-op same status)
    """
    all_transitions = TRANSITION_MATRIX.get(current_status, [])
    # Filter out the no-op transition (same status)
    return [s for s in all_transitions if s != current_status]


# Status sort order for list queries
# Lower number = higher priority (shown first)
# CR-004 Phase 4: Simplified for 4-state model
STATUS_SORT_ORDER: dict[LifecycleStatus, int] = {
    LifecycleStatus.REVIEW: 1,        # Needs review decision - action required
    LifecycleStatus.APPROVED: 2,      # Ready for implementation
    LifecycleStatus.DRAFT: 3,         # Backlog
    LifecycleStatus.DEPRECATED: 4,    # Retired - excluded from default queries
}
