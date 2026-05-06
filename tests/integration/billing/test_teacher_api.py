"""
Integration tests for teacher-specific API endpoints.

Tests cover:
- Teacher assigned students endpoint
- Permission enforcement (teacher-only)
- Student assignment filtering
- School isolation
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def api_client():
    """Create an API client for testing."""
    return APIClient()


@pytest.fixture
def authenticated_teacher_client(api_client, teacher_user):
    """Create an authenticated API client with teacher user."""
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def authenticated_management_client(api_client, management_user):
    """Create an authenticated API client with management user."""
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.mark.django_db
class TestTeacherAssignedStudentsAPI:
    """Tests for /api/billing/teacher/students/ endpoint."""

    def test_teacher_can_get_assigned_students(
        self, authenticated_teacher_client, teacher_user, school
    ):
        """Teachers can retrieve their assigned students."""
        # Create students assigned to this teacher
        student1 = User.objects.create(
            email='student1@test.com',
            first_name='Alice',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )
        student2 = User.objects.create(
            email='student2@test.com',
            first_name='Bob',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )

        # Assign students to teacher
        teacher_user.assigned_students.add(student1, student2)

        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

        # Verify both students are returned
        student_emails = [s['email'] for s in response.data]
        assert 'student1@test.com' in student_emails
        assert 'student2@test.com' in student_emails

    def test_teacher_only_sees_their_assigned_students(
        self, authenticated_teacher_client, teacher_user, school
    ):
        """Teachers only see students assigned to them, not other students."""
        # Create student assigned to this teacher
        assigned_student = User.objects.create(
            email='assigned@test.com',
            first_name='Assigned',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )
        teacher_user.assigned_students.add(assigned_student)

        # Create another teacher and their student
        other_teacher = User.objects.create(
            email='other_teacher@test.com',
            first_name='Other',
            last_name='Teacher',
            user_type='teacher',
            is_approved=True,
            school=school
        )
        other_student = User.objects.create(
            email='other@test.com',
            first_name='Other',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )
        other_teacher.assigned_students.add(other_student)

        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['email'] == 'assigned@test.com'

    def test_teacher_does_not_see_inactive_students(
        self, authenticated_teacher_client, teacher_user, school
    ):
        """Inactive students are filtered out from teacher's assigned students."""
        # Create active student
        active_student = User.objects.create(
            email='active@test.com',
            first_name='Active',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )

        # Create inactive student
        inactive_student = User.objects.create(
            email='inactive@test.com',
            first_name='Inactive',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=False,  # Inactive
            school=school
        )

        # Assign both to teacher
        teacher_user.assigned_students.add(active_student, inactive_student)

        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['email'] == 'active@test.com'

    def test_management_cannot_access_teacher_endpoint(
        self, authenticated_management_client
    ):
        """Management users cannot access teacher-specific endpoint."""
        url = reverse('teacher_assigned_students')
        response = authenticated_management_client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert 'error' in response.data
        assert 'Teacher access required' in response.data['error']

    def test_unauthenticated_user_cannot_access(self, api_client):
        """Unauthenticated users cannot access teacher endpoint."""
        url = reverse('teacher_assigned_students')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_teacher_with_no_assigned_students_gets_empty_list(
        self, authenticated_teacher_client, teacher_user
    ):
        """Teachers with no assigned students receive an empty list."""
        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0
        assert response.data == []

    def test_response_includes_student_details(
        self, authenticated_teacher_client, teacher_user, school
    ):
        """Response includes all necessary student details."""
        student = User.objects.create(
            email='student@test.com',
            first_name='Test',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )
        teacher_user.assigned_students.add(student)

        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

        student_data = response.data[0]
        assert student_data['email'] == 'student@test.com'
        assert student_data['first_name'] == 'Test'
        assert student_data['last_name'] == 'Student'
        assert student_data['user_type'] == 'student'
        assert 'id' in student_data


@pytest.mark.django_db
class TestTeacherListAuthentication:
    """SEC-03: teacher_list and teacher_detail require authentication."""

    def test_unauthenticated_teacher_list_returns_401(self, api_client):
        """
        SEC-03: Unauthenticated GET to /api/billing/teachers/ must return 401, not teacher PII.
        Currently FAILS — DRF default IsAuthenticatedOrReadOnly allows GET.
        """
        url = reverse('teacher_list')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unauthenticated_teacher_detail_returns_401(self, api_client, school):
        """
        SEC-03: Unauthenticated GET to /api/billing/teachers/<pk>/ must return 401.
        Currently FAILS — public teacher_detail returns full UserSerializer to anonymous callers.
        """
        teacher = User.objects.create_user(
            email="pub_teacher@test.com", password="test123",
            user_type="teacher", school=school, is_approved=True
        )
        url = reverse('teacher_detail', kwargs={'pk': teacher.id})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
