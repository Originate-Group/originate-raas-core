"""Tests for state machine validation.

CR-004 Phase 4: Requirements use simplified 4-state model:
- draft → review → approved → deprecated

Implementation states (in_progress, implemented, validated, deployed) are now
tracked on Work Items, not Requirements.
"""
import pytest
from tarka_core.models import LifecycleStatus
from tarka_core.state_machine import (
    is_transition_valid,
    validate_transition,
    StateTransitionError,
    get_allowed_transitions
)


class TestStateTransitions:
    """Test state machine transition validation (CR-004 Phase 4: 4-state model)."""

    def test_valid_forward_transitions(self):
        """Test that valid forward transitions are allowed."""
        # Draft → Review
        assert is_transition_valid(LifecycleStatus.DRAFT, LifecycleStatus.REVIEW)
        validate_transition(LifecycleStatus.DRAFT, LifecycleStatus.REVIEW)  # Should not raise

        # Review → Approved
        assert is_transition_valid(LifecycleStatus.REVIEW, LifecycleStatus.APPROVED)
        validate_transition(LifecycleStatus.REVIEW, LifecycleStatus.APPROVED)

    def test_valid_back_transitions(self):
        """Test that valid back-transitions are allowed."""
        # Review → Draft (needs more work)
        assert is_transition_valid(LifecycleStatus.REVIEW, LifecycleStatus.DRAFT)
        validate_transition(LifecycleStatus.REVIEW, LifecycleStatus.DRAFT)

        # Approved → Draft (major changes needed)
        assert is_transition_valid(LifecycleStatus.APPROVED, LifecycleStatus.DRAFT)
        validate_transition(LifecycleStatus.APPROVED, LifecycleStatus.DRAFT)

        # Approved → Review (needs re-review after changes)
        assert is_transition_valid(LifecycleStatus.APPROVED, LifecycleStatus.REVIEW)
        validate_transition(LifecycleStatus.APPROVED, LifecycleStatus.REVIEW)

    def test_deprecated_transitions(self):
        """Test deprecated (soft retirement) transitions."""
        # Review → Deprecated (RAAS-FEAT-080)
        assert is_transition_valid(LifecycleStatus.REVIEW, LifecycleStatus.DEPRECATED)
        validate_transition(LifecycleStatus.REVIEW, LifecycleStatus.DEPRECATED)

        # Approved → Deprecated (RAAS-FEAT-080)
        assert is_transition_valid(LifecycleStatus.APPROVED, LifecycleStatus.DEPRECATED)
        validate_transition(LifecycleStatus.APPROVED, LifecycleStatus.DEPRECATED)

    def test_noop_transitions_allowed(self):
        """Test that no-op transitions (same status) are always allowed."""
        for status in LifecycleStatus:
            assert is_transition_valid(status, status)
            validate_transition(status, status)  # Should not raise

    def test_invalid_skip_review_transition(self):
        """Test that skipping review (Draft → Approved) is blocked."""
        assert not is_transition_valid(LifecycleStatus.DRAFT, LifecycleStatus.APPROVED)

        with pytest.raises(StateTransitionError) as exc_info:
            validate_transition(LifecycleStatus.DRAFT, LifecycleStatus.APPROVED)

        error = exc_info.value
        assert error.current_status == LifecycleStatus.DRAFT
        assert error.requested_status == LifecycleStatus.APPROVED
        assert "must be reviewed before approval" in str(error).lower()

    def test_draft_cannot_be_deprecated(self):
        """Test that draft requirements cannot be deprecated directly."""
        assert not is_transition_valid(LifecycleStatus.DRAFT, LifecycleStatus.DEPRECATED)

        with pytest.raises(StateTransitionError):
            validate_transition(LifecycleStatus.DRAFT, LifecycleStatus.DEPRECATED)

    def test_deprecated_is_terminal(self):
        """Test that deprecated status cannot transition to other statuses."""
        # Only transition from deprecated to deprecated (no-op) is allowed
        assert is_transition_valid(LifecycleStatus.DEPRECATED, LifecycleStatus.DEPRECATED)

        # All other transitions from deprecated should be blocked
        for status in LifecycleStatus:
            if status != LifecycleStatus.DEPRECATED:
                assert not is_transition_valid(LifecycleStatus.DEPRECATED, status)

                with pytest.raises(StateTransitionError) as exc_info:
                    validate_transition(LifecycleStatus.DEPRECATED, status)

                assert "terminal" in str(exc_info.value).lower() or "cannot" in str(exc_info.value).lower()

    def test_get_allowed_transitions(self):
        """Test getting allowed transitions from each state."""
        # Draft can go to Review (no-op excluded)
        assert get_allowed_transitions(LifecycleStatus.DRAFT) == [LifecycleStatus.REVIEW]

        # Review can go to Draft, Approved, or Deprecated (no-op excluded)
        allowed = get_allowed_transitions(LifecycleStatus.REVIEW)
        assert set(allowed) == {LifecycleStatus.DRAFT, LifecycleStatus.APPROVED, LifecycleStatus.DEPRECATED}

        # Approved can go to Draft, Review, or Deprecated (no-op excluded)
        allowed = get_allowed_transitions(LifecycleStatus.APPROVED)
        assert set(allowed) == {LifecycleStatus.DRAFT, LifecycleStatus.REVIEW, LifecycleStatus.DEPRECATED}

        # Deprecated has no allowed transitions (terminal state, no-op excluded)
        assert get_allowed_transitions(LifecycleStatus.DEPRECATED) == []

    def test_state_transition_error_attributes(self):
        """Test that StateTransitionError contains all required attributes."""
        with pytest.raises(StateTransitionError) as exc_info:
            validate_transition(LifecycleStatus.DRAFT, LifecycleStatus.APPROVED)

        error = exc_info.value
        assert hasattr(error, 'current_status')
        assert hasattr(error, 'requested_status')
        assert hasattr(error, 'allowed_transitions')
        assert error.current_status == LifecycleStatus.DRAFT
        assert error.requested_status == LifecycleStatus.APPROVED
        assert isinstance(error.allowed_transitions, list)


class TestFourStateModelEnforcement:
    """Test that only the 4-state model is enforced (CR-004 Phase 4)."""

    def test_only_four_states_exist(self):
        """Verify only 4 states exist in the enum."""
        expected_states = {'draft', 'review', 'approved', 'deprecated'}
        actual_states = {status.value for status in LifecycleStatus}
        assert actual_states == expected_states, (
            f"Expected 4 states {expected_states}, but found {actual_states}. "
            "CR-004 Phase 4 requires only draft/review/approved/deprecated."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
