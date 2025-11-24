"""Tests for hierarchy validation."""
import pytest
from uuid import uuid4
from unittest.mock import MagicMock
from raas_core.models import RequirementType, Requirement
from raas_core.hierarchy_validation import (
    validate_parent_type,
    HierarchyValidationError,
    find_hierarchy_violations,
    VALID_PARENT_TYPES,
)


class TestValidParentTypes:
    """Test the VALID_PARENT_TYPES mapping."""

    def test_valid_parent_types_mapping(self):
        """Test that the canonical parent type mapping is correct."""
        assert VALID_PARENT_TYPES[RequirementType.EPIC] is None
        assert VALID_PARENT_TYPES[RequirementType.COMPONENT] == RequirementType.EPIC
        assert VALID_PARENT_TYPES[RequirementType.FEATURE] == RequirementType.COMPONENT
        assert VALID_PARENT_TYPES[RequirementType.REQUIREMENT] == RequirementType.FEATURE

    def test_all_requirement_types_covered(self):
        """Test that all requirement types have validation rules."""
        for req_type in RequirementType:
            assert req_type in VALID_PARENT_TYPES


class TestValidateParentType:
    """Test parent type validation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.db = MagicMock()

    def test_epic_without_parent_valid(self):
        """Test that Epic without parent is valid."""
        # Should not raise
        validate_parent_type(self.db, RequirementType.EPIC, None)

    def test_epic_with_parent_invalid(self):
        """Test that Epic with parent is invalid."""
        parent_id = uuid4()

        with pytest.raises(HierarchyValidationError) as exc_info:
            validate_parent_type(self.db, RequirementType.EPIC, parent_id)

        error = exc_info.value
        assert error.child_type == RequirementType.EPIC
        assert error.expected_parent_type is None
        assert error.parent_id == parent_id
        assert "top-level" in error.message.lower()
        assert "cannot create epic with a parent" in error.message.lower()

    def test_component_without_parent_invalid(self):
        """Test that Component without parent is invalid."""
        with pytest.raises(HierarchyValidationError) as exc_info:
            validate_parent_type(self.db, RequirementType.COMPONENT, None)

        error = exc_info.value
        assert error.child_type == RequirementType.COMPONENT
        assert error.expected_parent_type == RequirementType.EPIC
        assert "must have a epic as their parent" in error.message.lower()

    def test_component_with_epic_parent_valid(self):
        """Test that Component with Epic parent is valid."""
        parent_id = uuid4()
        parent = MagicMock()
        parent.type = RequirementType.EPIC
        parent.title = "Test Epic"
        self.db.query.return_value.filter.return_value.first.return_value = parent

        # Should not raise
        validate_parent_type(self.db, RequirementType.COMPONENT, parent_id)

    def test_component_with_component_parent_invalid(self):
        """Test that Component with Component parent is invalid."""
        parent_id = uuid4()
        parent = MagicMock()
        parent.type = RequirementType.COMPONENT
        parent.title = "Test Component"
        parent.id = parent_id
        self.db.query.return_value.filter.return_value.first.return_value = parent

        with pytest.raises(HierarchyValidationError) as exc_info:
            validate_parent_type(self.db, RequirementType.COMPONENT, parent_id)

        error = exc_info.value
        assert error.child_type == RequirementType.COMPONENT
        assert error.expected_parent_type == RequirementType.EPIC
        assert error.actual_parent_type == RequirementType.COMPONENT
        assert error.parent_id == parent_id
        assert error.parent_title == "Test Component"
        assert "cannot create component as child of component" in error.message.lower()

    def test_feature_with_component_parent_valid(self):
        """Test that Feature with Component parent is valid."""
        parent_id = uuid4()
        parent = MagicMock()
        parent.type = RequirementType.COMPONENT
        parent.title = "Test Component"
        self.db.query.return_value.filter.return_value.first.return_value = parent

        # Should not raise
        validate_parent_type(self.db, RequirementType.FEATURE, parent_id)

    def test_feature_with_epic_parent_invalid(self):
        """Test that Feature with Epic parent is invalid."""
        parent_id = uuid4()
        parent = MagicMock()
        parent.type = RequirementType.EPIC
        parent.title = "Test Epic"
        parent.id = parent_id
        self.db.query.return_value.filter.return_value.first.return_value = parent

        with pytest.raises(HierarchyValidationError) as exc_info:
            validate_parent_type(self.db, RequirementType.FEATURE, parent_id)

        error = exc_info.value
        assert error.child_type == RequirementType.FEATURE
        assert error.expected_parent_type == RequirementType.COMPONENT
        assert error.actual_parent_type == RequirementType.EPIC
        assert "cannot create feature as child of epic" in error.message.lower()

    def test_requirement_with_feature_parent_valid(self):
        """Test that Requirement with Feature parent is valid."""
        parent_id = uuid4()
        parent = MagicMock()
        parent.type = RequirementType.FEATURE
        parent.title = "Test Feature"
        self.db.query.return_value.filter.return_value.first.return_value = parent

        # Should not raise
        validate_parent_type(self.db, RequirementType.REQUIREMENT, parent_id)

    def test_requirement_with_component_parent_invalid(self):
        """Test that Requirement with Component parent is invalid (most common violation)."""
        parent_id = uuid4()
        parent = MagicMock()
        parent.type = RequirementType.COMPONENT
        parent.title = "Test Component"
        parent.id = parent_id
        self.db.query.return_value.filter.return_value.first.return_value = parent

        with pytest.raises(HierarchyValidationError) as exc_info:
            validate_parent_type(self.db, RequirementType.REQUIREMENT, parent_id)

        error = exc_info.value
        assert error.child_type == RequirementType.REQUIREMENT
        assert error.expected_parent_type == RequirementType.FEATURE
        assert error.actual_parent_type == RequirementType.COMPONENT
        assert "cannot create requirement as child of component" in error.message.lower()
        assert "must have a feature as their parent" in error.message.lower()

    def test_requirement_without_parent_invalid(self):
        """Test that Requirement without parent is invalid."""
        with pytest.raises(HierarchyValidationError) as exc_info:
            validate_parent_type(self.db, RequirementType.REQUIREMENT, None)

        error = exc_info.value
        assert error.child_type == RequirementType.REQUIREMENT
        assert error.expected_parent_type == RequirementType.FEATURE
        assert "must have a feature as their parent" in error.message.lower()

    def test_parent_not_found_raises_value_error(self):
        """Test that non-existent parent raises ValueError (404 case)."""
        parent_id = uuid4()
        self.db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError) as exc_info:
            validate_parent_type(self.db, RequirementType.COMPONENT, parent_id)

        assert "not found" in str(exc_info.value).lower()
        assert str(parent_id) in str(exc_info.value)

    def test_error_message_includes_context(self):
        """Test that error messages include full context for remediation."""
        parent_id = uuid4()
        parent = MagicMock()
        parent.type = RequirementType.EPIC
        parent.title = "Authentication System"
        parent.id = parent_id
        self.db.query.return_value.filter.return_value.first.return_value = parent

        with pytest.raises(HierarchyValidationError) as exc_info:
            validate_parent_type(self.db, RequirementType.REQUIREMENT, parent_id)

        error = exc_info.value
        # Error message should include:
        # - Child type being created
        # - Actual parent type
        # - Expected parent type
        # - Parent title for context
        # - Parent ID for reference
        assert "requirement" in error.message.lower()
        assert "epic" in error.message.lower()
        assert "feature" in error.message.lower()
        assert "Authentication System" in error.message
        assert str(parent_id) in error.message


class TestFindHierarchyViolations:
    """Test finding existing hierarchy violations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.db = MagicMock()

    def test_no_violations_returns_empty_list(self):
        """Test that valid hierarchy returns no violations."""
        # Create valid hierarchy: Epic -> Component -> Feature -> Requirement
        epic = MagicMock(spec=Requirement)
        epic.id = uuid4()
        epic.type = RequirementType.EPIC
        epic.parent_id = None
        epic.human_readable_id = "TEST-EPIC-001"
        epic.title = "Test Epic"

        component = MagicMock(spec=Requirement)
        component.id = uuid4()
        component.type = RequirementType.COMPONENT
        component.parent_id = epic.id
        component.human_readable_id = "TEST-COMP-001"
        component.title = "Test Component"

        feature = MagicMock(spec=Requirement)
        feature.id = uuid4()
        feature.type = RequirementType.FEATURE
        feature.parent_id = component.id
        feature.human_readable_id = "TEST-FEAT-001"
        feature.title = "Test Feature"

        requirement = MagicMock(spec=Requirement)
        requirement.id = uuid4()
        requirement.type = RequirementType.REQUIREMENT
        requirement.parent_id = feature.id
        requirement.human_readable_id = "TEST-REQ-001"
        requirement.title = "Test Requirement"

        # Mock database query to return all requirements
        self.db.query.return_value.all.return_value = [epic, component, feature, requirement]

        # Mock individual parent lookups
        def mock_filter_first(id_val):
            if id_val == epic.id:
                return epic
            elif id_val == component.id:
                return component
            elif id_val == feature.id:
                return feature
            return None

        # Setup query chain for parent lookups
        query_mock = MagicMock()
        filter_mock = MagicMock()
        query_mock.filter.return_value = filter_mock

        # Define side effect for first() based on filter condition
        parents = {
            epic.id: epic,
            component.id: component,
            feature.id: feature,
        }

        def first_side_effect():
            # Extract the UUID from the filter call (hacky but works for tests)
            return parents.get(component.parent_id) or parents.get(feature.parent_id) or parents.get(requirement.parent_id)

        # Use a more sophisticated mock
        self.db.query.return_value.filter.return_value.first.side_effect = [
            None,  # Epic has no parent
            epic,  # Component's parent is Epic
            component,  # Feature's parent is Component
            feature,  # Requirement's parent is Feature
        ]

        violations = find_hierarchy_violations(self.db, None)
        assert len(violations) == 0

    def test_requirement_under_component_violation(self):
        """Test that Requirement directly under Component is detected."""
        component = MagicMock(spec=Requirement)
        component.id = uuid4()
        component.type = RequirementType.COMPONENT
        component.parent_id = uuid4()  # Has an epic parent
        component.human_readable_id = "TEST-COMP-001"
        component.title = "Test Component"

        requirement = MagicMock(spec=Requirement)
        requirement.id = uuid4()
        requirement.type = RequirementType.REQUIREMENT
        requirement.parent_id = component.id  # VIOLATION: Should have Feature parent
        requirement.human_readable_id = "TEST-REQ-001"
        requirement.title = "Test Requirement"

        self.db.query.return_value.all.return_value = [component, requirement]

        # Mock parent lookups
        self.db.query.return_value.filter.return_value.first.side_effect = [
            MagicMock(type=RequirementType.EPIC),  # Component's parent is Epic (valid)
            component,  # Requirement's parent is Component (VIOLATION)
        ]

        violations = find_hierarchy_violations(self.db, None)

        assert len(violations) == 1
        violation = violations[0]
        assert violation["requirement_type"] == "requirement"
        assert violation["parent_type"] == "component"
        assert violation["expected_parent_type"] == "feature"
        assert "cannot create requirement as child of component" in violation["violation"].lower()

    def test_epic_with_parent_violation(self):
        """Test that Epic with parent is detected."""
        parent = MagicMock(spec=Requirement)
        parent.id = uuid4()
        parent.type = RequirementType.EPIC
        parent.title = "Parent Epic"

        epic = MagicMock(spec=Requirement)
        epic.id = uuid4()
        epic.type = RequirementType.EPIC
        epic.parent_id = parent.id  # VIOLATION: Epics cannot have parents
        epic.human_readable_id = "TEST-EPIC-002"
        epic.title = "Child Epic"

        self.db.query.return_value.all.return_value = [parent, epic]
        self.db.query.return_value.filter.return_value.first.side_effect = [
            None,  # First epic has no parent (valid)
            parent,  # Second epic has parent (VIOLATION)
        ]

        violations = find_hierarchy_violations(self.db, None)

        assert len(violations) == 1
        violation = violations[0]
        assert violation["requirement_type"] == "epic"
        assert "cannot create epic with a parent" in violation["violation"].lower()

    def test_orphaned_requirement_detected(self):
        """Test that requirement with missing parent is detected."""
        requirement = MagicMock(spec=Requirement)
        requirement.id = uuid4()
        requirement.type = RequirementType.REQUIREMENT
        requirement.parent_id = uuid4()  # Parent doesn't exist
        requirement.human_readable_id = "TEST-REQ-001"
        requirement.title = "Orphaned Requirement"

        self.db.query.return_value.all.return_value = [requirement]
        self.db.query.return_value.filter.return_value.first.return_value = None  # Parent not found

        violations = find_hierarchy_violations(self.db, None)

        assert len(violations) == 1
        violation = violations[0]
        assert "not found" in violation["violation"].lower()
        assert "orphaned" in violation["violation"].lower()

    def test_project_filter_applied(self):
        """Test that project_id filter is applied correctly."""
        project_id = uuid4()

        requirement = MagicMock(spec=Requirement)
        requirement.id = uuid4()
        requirement.type = RequirementType.REQUIREMENT
        requirement.parent_id = None  # VIOLATION: Requirement needs parent
        requirement.project_id = project_id
        requirement.human_readable_id = "TEST-REQ-001"
        requirement.title = "Test Requirement"

        query_mock = MagicMock()
        filter_mock = MagicMock()
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = [requirement]

        self.db.query.return_value = query_mock

        find_hierarchy_violations(self.db, project_id)

        # Verify project filter was applied
        self.db.query.return_value.filter.assert_called()


class TestHierarchyValidationErrorAttributes:
    """Test HierarchyValidationError attributes."""

    def test_error_has_all_attributes(self):
        """Test that HierarchyValidationError contains all expected attributes."""
        parent_id = uuid4()
        error = HierarchyValidationError(
            message="Test error message",
            child_type=RequirementType.REQUIREMENT,
            expected_parent_type=RequirementType.FEATURE,
            actual_parent_type=RequirementType.COMPONENT,
            parent_id=parent_id,
            parent_title="Test Component",
        )

        assert error.message == "Test error message"
        assert error.child_type == RequirementType.REQUIREMENT
        assert error.expected_parent_type == RequirementType.FEATURE
        assert error.actual_parent_type == RequirementType.COMPONENT
        assert error.parent_id == parent_id
        assert error.parent_title == "Test Component"

    def test_error_string_representation(self):
        """Test that error converts to string properly."""
        error = HierarchyValidationError(
            message="Test error message",
            child_type=RequirementType.REQUIREMENT,
            expected_parent_type=RequirementType.FEATURE,
        )

        assert str(error) == "Test error message"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
