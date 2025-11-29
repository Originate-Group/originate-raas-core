"""Tests for RBAC permission checking (RAAS-FEAT-048)."""
import pytest
from uuid import uuid4
from unittest.mock import MagicMock

from tarka_core.models import (
    RequirementType,
    ProjectRole,
    MemberRole,
    Requirement,
    Project,
    OrganizationMember,
    ProjectMember,
)
from tarka_core.permissions import (
    PermissionDeniedError,
    check_org_permission,
    check_project_permission,
    can_create_requirement,
    can_update_requirement,
    can_delete_requirement,
)


class TestOrganizationPermissions:
    """Test organization-level permission checks."""

    def setup_method(self):
        """Set up test fixtures."""
        self.db = MagicMock()
        self.user_id = uuid4()
        self.org_id = uuid4()

    def test_owner_has_all_permissions(self):
        """Test that organization owners have full permissions."""
        # Mock organization membership with owner role
        membership = MagicMock()
        membership.role = MemberRole.OWNER
        self.db.query.return_value.filter.return_value.first.return_value = membership

        # Should not raise
        check_org_permission(
            self.db, self.user_id, self.org_id, MemberRole.OWNER, "delete organization"
        )

    def test_admin_cannot_delete_organization(self):
        """Test that admins cannot delete organizations (owner-only)."""
        membership = MagicMock()
        membership.role = MemberRole.ADMIN
        self.db.query.return_value.filter.return_value.first.return_value = membership

        with pytest.raises(PermissionDeniedError) as exc_info:
            check_org_permission(
                self.db,
                self.user_id,
                self.org_id,
                MemberRole.OWNER,
                "delete organization",
            )

        error = exc_info.value
        assert error.required_role == "owner"
        assert error.current_role == "admin"
        assert "need owner role" in error.message.lower()

    def test_viewer_cannot_manage_organization(self):
        """Test that viewers cannot manage organization settings."""
        membership = MagicMock()
        membership.role = MemberRole.VIEWER
        self.db.query.return_value.filter.return_value.first.return_value = membership

        with pytest.raises(PermissionDeniedError) as exc_info:
            check_org_permission(
                self.db, self.user_id, self.org_id, MemberRole.ADMIN, "manage settings"
            )

        error = exc_info.value
        assert error.required_role == "admin"
        assert error.current_role == "viewer"

    def test_non_member_cannot_access_organization(self):
        """Test that non-members are denied access."""
        self.db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(PermissionDeniedError) as exc_info:
            check_org_permission(
                self.db, self.user_id, self.org_id, MemberRole.MEMBER, "view organization"
            )

        error = exc_info.value
        assert error.current_role is None
        assert "must be a member" in error.message.lower()


class TestProjectPermissions:
    """Test project-level permission checks."""

    def setup_method(self):
        """Set up test fixtures."""
        self.db = MagicMock()
        self.user_id = uuid4()
        self.project_id = uuid4()
        self.org_id = uuid4()

        # Mock project
        self.project = MagicMock()
        self.project.id = self.project_id
        self.project.organization_id = self.org_id

    def test_project_admin_has_full_permissions(self):
        """Test that project admins have full permissions."""
        # Mock project query
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.project,  # First call: get project
            MagicMock(role=ProjectRole.ADMIN),  # Second call: get project membership
        ]

        # Should not raise
        check_project_permission(
            self.db, self.user_id, self.project_id, ProjectRole.ADMIN, "manage project"
        )

    def test_editor_can_edit_but_not_admin(self):
        """Test that editors can edit but not admin."""
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.project,
            MagicMock(role=ProjectRole.EDITOR),
        ]

        # Editor should be able to edit
        check_project_permission(
            self.db, self.user_id, self.project_id, ProjectRole.EDITOR, "edit requirements"
        )

        # But not admin
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.project,
            MagicMock(role=ProjectRole.EDITOR),
        ]

        with pytest.raises(PermissionDeniedError) as exc_info:
            check_project_permission(
                self.db, self.user_id, self.project_id, ProjectRole.ADMIN, "manage project"
            )

        error = exc_info.value
        assert error.required_role == "admin"
        assert error.current_role == "editor"

    def test_viewer_cannot_edit(self):
        """Test that viewers cannot edit requirements."""
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.project,
            MagicMock(role=ProjectRole.VIEWER),
        ]

        with pytest.raises(PermissionDeniedError) as exc_info:
            check_project_permission(
                self.db, self.user_id, self.project_id, ProjectRole.EDITOR, "edit requirements"
            )

        error = exc_info.value
        assert error.required_role == "editor"
        assert error.current_role == "viewer"

    def test_org_admin_has_implicit_project_admin_access(self):
        """Test that organization admins have implicit project admin access."""
        # Mock: No project membership, but org admin
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.project,  # Project exists
            None,  # No project membership
            MagicMock(role=MemberRole.ADMIN),  # But org admin
        ]

        # Should not raise (org admin has implicit access)
        check_project_permission(
            self.db, self.user_id, self.project_id, ProjectRole.ADMIN, "manage project"
        )

    def test_org_owner_has_implicit_project_admin_access(self):
        """Test that organization owners have implicit project admin access."""
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.project,
            None,  # No project membership
            MagicMock(role=MemberRole.OWNER),  # But org owner
        ]

        # Should not raise
        check_project_permission(
            self.db, self.user_id, self.project_id, ProjectRole.ADMIN, "manage project"
        )


class TestRequirementPermissions:
    """Test requirement-specific permission checks."""

    def setup_method(self):
        """Set up test fixtures."""
        self.db = MagicMock()
        self.user_id = uuid4()
        self.project_id = uuid4()
        self.requirement_id = uuid4()
        self.org_id = uuid4()

        # Mock requirement
        self.requirement = MagicMock()
        self.requirement.id = self.requirement_id
        self.requirement.project_id = self.project_id

        # Mock project
        self.project = MagicMock()
        self.project.id = self.project_id
        self.project.organization_id = self.org_id

    def test_editor_can_create_requirement(self):
        """Test that editors can create requirements."""
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.project,
            MagicMock(role=ProjectRole.EDITOR),
        ]

        assert can_create_requirement(self.db, self.user_id, self.project_id)

    def test_viewer_cannot_create_requirement(self):
        """Test that viewers cannot create requirements."""
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.project,
            MagicMock(role=ProjectRole.VIEWER),
        ]

        with pytest.raises(PermissionDeniedError) as exc_info:
            can_create_requirement(self.db, self.user_id, self.project_id)

        error = exc_info.value
        assert "editor" in error.message.lower()

    def test_editor_can_update_requirement(self):
        """Test that editors can update requirements."""
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.requirement,  # Get requirement
            self.project,  # Get project
            MagicMock(role=ProjectRole.EDITOR),  # User is editor
        ]

        assert can_update_requirement(self.db, self.user_id, self.requirement_id)

    def test_viewer_cannot_update_requirement(self):
        """Test that viewers cannot update requirements."""
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.requirement,
            self.project,
            MagicMock(role=ProjectRole.VIEWER),
        ]

        with pytest.raises(PermissionDeniedError):
            can_update_requirement(self.db, self.user_id, self.requirement_id)

    def test_admin_can_delete_requirement(self):
        """Test that project admins can delete requirements."""
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.requirement,
            self.project,
            MagicMock(role=ProjectRole.ADMIN),
        ]

        assert can_delete_requirement(self.db, self.user_id, self.requirement_id)

    def test_editor_cannot_delete_requirement(self):
        """Test that editors cannot delete requirements (admin-only)."""
        self.db.query.return_value.filter.return_value.first.side_effect = [
            self.requirement,
            self.project,
            MagicMock(role=ProjectRole.EDITOR),
        ]

        with pytest.raises(PermissionDeniedError) as exc_info:
            can_delete_requirement(self.db, self.user_id, self.requirement_id)

        error = exc_info.value
        assert error.required_role == "admin"
        assert error.current_role == "editor"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
