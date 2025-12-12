"""
Unit tests for user permission system and role-based access control.

CRITICAL: These tests ensure teachers can only access their own data
and management has full access.
"""

import pytest
from django.test import RequestFactory
from django.http import HttpResponse
from custom_auth.decorators import role_required, owns_resource_or_management
from billing.models import User, Lesson
from datetime import datetime


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
class TestOwnsResourceOrManagement:
    """Test owns_resource_or_management decorator for resource ownership checks."""

    def test_teacher_can_access_own_resource(self, teacher_user, student_user, request_factory):
        """Teachers can access their own resources."""

        # Create a lesson taught by this teacher
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            rate=80,
            duration=1.0,
            scheduled_date=datetime.now(),
            status="confirmed"
        )

        @owns_resource_or_management('teacher')
        def lesson_detail_view(request, pk):
            # In real view, this would fetch the lesson by pk
            # For test, we'll simulate by attaching it to request
            request.resource = lesson
            return HttpResponse(f"Lesson {pk}")

        request = request_factory.get(f'/lessons/{lesson.id}/')
        request.user = teacher_user
        request.resource = lesson  # Simulating the resource being fetched

        response = lesson_detail_view(request, pk=lesson.id)
        assert response.status_code == 200

    def test_teacher_cannot_access_other_teachers_resource(self, teacher_user, student_user, request_factory, db):
        """Teachers cannot access resources owned by other teachers.

        Note: This tests the decorator's role checking. In practice, views would
        also check resource ownership explicitly (e.g., filtering querysets by teacher).
        """

        # Create another teacher
        other_teacher = User.objects.create_user(
            email="other@test.com",
            password="testpass123",
            user_type="teacher",
            hourly_rate=80,
            is_approved=True
        )

        # Create a lesson taught by the OTHER teacher
        lesson = Lesson.objects.create(
            teacher=other_teacher,  # Different teacher
            student=student_user,
            rate=80,
            duration=1.0,
            scheduled_date=datetime.now(),
            status="confirmed"
        )

        @owns_resource_or_management('teacher')
        def lesson_detail_view(request, pk):
            # In real views, we'd check: if request.resource.teacher != request.user
            # The decorator sets up resource_owner, but views must check ownership
            if hasattr(request, 'resource_owner'):
                # Simulate view-level ownership check
                if lesson.teacher != request.resource_owner:
                    return HttpResponse("Forbidden", status=403)
            return HttpResponse(f"Lesson {pk}")

        request = request_factory.get(f'/lessons/{lesson.id}/')
        request.user = teacher_user  # Current teacher trying to access

        response = lesson_detail_view(request, pk=lesson.id)
        # Should return 403 - teacher doesn't own this resource
        assert response.status_code == 403

    def test_management_can_access_any_resource(self, management_user, teacher_user, student_user, request_factory):
        """Management can access any resource regardless of ownership."""

        # Create a lesson taught by a teacher
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            rate=80,
            duration=1.0,
            scheduled_date=datetime.now(),
            status="confirmed"
        )

        @owns_resource_or_management('teacher')
        def lesson_detail_view(request, pk):
            request.resource = lesson
            return HttpResponse(f"Lesson {pk}")

        request = request_factory.get(f'/lessons/{lesson.id}/')
        request.user = management_user  # Management accessing teacher's resource
        request.resource = lesson

        response = lesson_detail_view(request, pk=lesson.id)
        # Management should have access even though they don't "own" it
        assert response.status_code == 200


@pytest.mark.django_db
class TestUserApprovalSystem:
    """Test that approval status affects access."""

    def test_management_auto_approved(self, db):
        """Management users are auto-approved upon creation."""
        manager = User.objects.create_user(
            email="newmanager@test.com",
            password="testpass123",
            user_type="management"
        )

        # Management should be auto-approved
        assert manager.is_approved is True

    def test_teacher_not_auto_approved(self, db):
        """Teachers are not auto-approved and require management approval."""
        teacher = User.objects.create_user(
            email="newteacher@test.com",
            password="testpass123",
            user_type="teacher"
        )

        # Teachers should NOT be auto-approved
        assert teacher.is_approved is False

    def test_student_not_auto_approved(self, db):
        """Students are not auto-approved and require management approval."""
        student = User.objects.create_user(
            email="newstudent@test.com",
            password="testpass123",
            user_type="student"
        )

        # Students should NOT be auto-approved
        assert student.is_approved is False
