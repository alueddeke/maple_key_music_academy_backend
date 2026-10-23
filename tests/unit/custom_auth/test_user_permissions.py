"""
Unit tests for user permission system and role-based access control.

CRITICAL: These tests ensure teachers can only access their own data
and management has full access.
"""

import pytest
from django.test import RequestFactory
from django.http import HttpResponse
from custom_auth.decorators import role_required
from billing.models import User


@pytest.fixture
def request_factory():
    """Provide Django RequestFactory for creating mock requests."""
    return RequestFactory()


@pytest.mark.django_db
class TestRoleRequiredDecorator:
    """Test role_required decorator enforces user type restrictions."""

    def test_management_can_access_management_only_view(self, management_user, request_factory):
        """Management users can access management-only endpoints."""

        @role_required('management')
        def management_view(request):
            return HttpResponse("Success")

        request = request_factory.get('/')
        request.user = management_user

        response = management_view(request)
        assert response.status_code == 200
        assert response.content == b"Success"

    def test_teacher_cannot_access_management_only_view(self, teacher_user, request_factory):
        """Teachers cannot access management-only endpoints."""

        @role_required('management')
        def management_view(request):
            return HttpResponse("Success")

        request = request_factory.get('/')
        request.user = teacher_user

        response = management_view(request)
        # Should return 403 Forbidden
        assert response.status_code == 403

    def test_teacher_can_access_teacher_allowed_view(self, teacher_user, request_factory):
        """Teachers can access endpoints that allow their role."""

        @role_required('teacher', 'management')
        def teacher_or_management_view(request):
            return HttpResponse("Success")

        request = request_factory.get('/')
        request.user = teacher_user

        response = teacher_or_management_view(request)
        assert response.status_code == 200

    def test_student_cannot_access_teacher_only_view(self, student_user, request_factory):
        """Students cannot access teacher-only endpoints."""

        @role_required('teacher')
        def teacher_view(request):
            return HttpResponse("Success")

        request = request_factory.get('/')
        request.user = student_user

        response = teacher_view(request)
        assert response.status_code == 403

    def test_unapproved_teacher_cannot_access_protected_view(self, unapproved_teacher, request_factory):
        """Unapproved users cannot access protected endpoints even with correct role."""

        @role_required('teacher')
        def teacher_view(request):
            return HttpResponse("Success")

        request = request_factory.get('/')
        request.user = unapproved_teacher

        response = teacher_view(request)
        # Should return 403 because user is not approved
        assert response.status_code == 403


@pytest.mark.django_db
class TestUserApprovalSystem:
    """Test that approval status affects access."""

    def test_management_auto_approved(self, school):
        """Management users are auto-approved upon creation."""
        manager = User.objects.create_user(
            email="newmanager@test.com",
            password="testpass123",
            user_type="management",
            school=school
        )

        # Management should be auto-approved
        assert manager.is_approved is True

    def test_teacher_not_auto_approved(self, school):
        """Teachers are not auto-approved and require management approval."""
        teacher = User.objects.create_user(
            email="newteacher@test.com",
            password="testpass123",
            user_type="teacher",
            school=school
        )

        # Teachers should NOT be auto-approved
        assert teacher.is_approved is False

    def test_student_not_auto_approved(self, school):
        """Students are not auto-approved and require management approval."""
        student = User.objects.create_user(
            email="newstudent@test.com",
            password="testpass123",
            user_type="student",
            school=school
        )

        # Students should NOT be auto-approved
        assert student.is_approved is False
