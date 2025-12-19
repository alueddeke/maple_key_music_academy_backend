"""
Integration tests for management API endpoints.

Tests cover:
- Global rate settings CRUD operations
- Teacher management and rate updates
- Permission enforcement (management-only)
- Rate locking mechanism (existing lessons unchanged)
"""

import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from billing.models import GlobalRateSettings, Lesson, Invoice
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def api_client():
    """Create an API client for testing."""
    return APIClient()


@pytest.fixture
def authenticated_management_client(api_client, management_user):
    """Create an authenticated API client with management user."""
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.fixture
def authenticated_teacher_client(api_client, teacher_user):
    """Create an authenticated API client with teacher user."""
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def global_rates(db):
    """Create or get global rate settings."""
    return GlobalRateSettings.get_settings()


@pytest.mark.django_db
class TestGlobalRateSettingsAPI:
    """Tests for /api/billing/management/global-rates/ endpoint."""

    def test_get_global_rates_as_management(self, authenticated_management_client, global_rates):
        """Management can retrieve global rate settings."""
        url = reverse('global_rate_settings')
        response = authenticated_management_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert 'online_teacher_rate' in response.data
        assert 'online_student_rate' in response.data
        assert 'inperson_student_rate' in response.data
        assert response.data['online_teacher_rate'] == '45.00'

    def test_get_global_rates_as_teacher_forbidden(self, authenticated_teacher_client):
        """Teachers cannot access global rate settings."""
        url = reverse('global_rate_settings')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_global_rates_unauthenticated(self, api_client):
        """Unauthenticated users cannot access global rate settings."""
        url = reverse('global_rate_settings')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_global_rates_as_management(self, authenticated_management_client, global_rates, management_user):
        """Management can update global rate settings."""
        url = reverse('global_rate_settings')
        data = {
            'online_teacher_rate': '50.00',
            'online_student_rate': '65.00',
            'inperson_student_rate': '110.00'
        }
        response = authenticated_management_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['online_teacher_rate'] == '50.00'
        assert response.data['online_student_rate'] == '65.00'
        assert response.data['inperson_student_rate'] == '110.00'
        assert response.data['updated_by'] == management_user.id
        assert response.data['updated_by_name'] == 'Test Manager'

    def test_update_global_rates_as_teacher_forbidden(self, authenticated_teacher_client):
        """Teachers cannot update global rate settings."""
        url = reverse('global_rate_settings')
        data = {'online_teacher_rate': '100.00'}
        response = authenticated_teacher_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_update_global_rates_partial(self, authenticated_management_client, global_rates):
        """Management can partially update global rate settings."""
        url = reverse('global_rate_settings')
        data = {'online_teacher_rate': '55.00'}
        response = authenticated_management_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['online_teacher_rate'] == '55.00'
        # Other rates should remain unchanged
        assert response.data['online_student_rate'] == '60.00'


@pytest.mark.django_db
class TestTeacherManagementAPI:
    """Tests for /api/billing/management/teachers/ endpoints."""

    def test_list_teachers_as_management(self, authenticated_management_client, teacher_user):
        """Management can list all teachers with stats."""
        url = reverse('management_teacher_list')
        response = authenticated_management_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1
        teacher_data = response.data[0]
        assert teacher_data['email'] == teacher_user.email
        assert teacher_data['hourly_rate'] == '80.00'
        assert 'total_students' in teacher_data
        assert 'total_lessons' in teacher_data
        assert 'total_earnings' in teacher_data

    def test_list_teachers_as_teacher_forbidden(self, authenticated_teacher_client):
        """Teachers cannot list other teachers."""
        url = reverse('management_teacher_list')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_teacher_detail_as_management(self, authenticated_management_client, teacher_user):
        """Management can retrieve teacher details."""
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        response = authenticated_management_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['email'] == teacher_user.email
        assert response.data['hourly_rate'] == '80.00'
        assert 'total_students' in response.data
        assert 'recent_lessons' in response.data

    def test_update_teacher_rate_as_management(self, authenticated_management_client, teacher_user):
        """Management can update teacher hourly rate."""
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        data = {'hourly_rate': '90.00'}
        response = authenticated_management_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['hourly_rate'] == '90.00'

        # Verify database update
        teacher_user.refresh_from_db()
        assert teacher_user.hourly_rate == Decimal('90.00')

    def test_update_teacher_rate_as_teacher_forbidden(self, authenticated_teacher_client, teacher_user):
        """Teachers cannot update their own hourly rate."""
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        data = {'hourly_rate': '150.00'}
        response = authenticated_teacher_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestRateLockingMechanism:
    """Tests for rate locking - existing lessons should not be affected by rate changes."""

    def test_global_rate_change_does_not_affect_existing_online_lessons(
        self, authenticated_management_client, teacher_user, student_user, global_rates
    ):
        """Changing global online rates does not affect existing online lessons."""
        # Create an online lesson with current rate
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            duration=Decimal("1.0"),
            lesson_type="online",
            teacher_rate=Decimal("45.00"),  # Locked rate
            student_rate=Decimal("60.00"),
            status="completed"
        )
        original_teacher_rate = lesson.teacher_rate

        # Update global online teacher rate
        url = reverse('global_rate_settings')
        data = {'online_teacher_rate': '55.00'}
        response = authenticated_management_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Verify existing lesson rate unchanged (rate locking)
        lesson.refresh_from_db()
        assert lesson.teacher_rate == original_teacher_rate
        assert lesson.teacher_rate == Decimal("45.00")

    def test_teacher_rate_change_does_not_affect_existing_inperson_lessons(
        self, authenticated_management_client, teacher_user, student_user
    ):
        """Changing teacher hourly rate does not affect existing in-person lessons."""
        # Create an in-person lesson with current teacher rate
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            duration=Decimal("1.0"),
            lesson_type="in_person",
            teacher_rate=Decimal("80.00"),  # Locked at teacher's hourly_rate
            student_rate=Decimal("100.00"),
            status="completed"
        )
        original_teacher_rate = lesson.teacher_rate

        # Update teacher hourly rate
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        data = {'hourly_rate': '95.00'}
        response = authenticated_management_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Verify existing lesson rate unchanged (rate locking)
        lesson.refresh_from_db()
        assert lesson.teacher_rate == original_teacher_rate
        assert lesson.teacher_rate == Decimal("80.00")

    def test_new_online_lesson_uses_updated_global_rate(
        self, authenticated_management_client, teacher_user, student_user
    ):
        """New online lessons use the updated global rate."""
        # Update global online teacher rate
        url = reverse('global_rate_settings')
        data = {'online_teacher_rate': '50.00'}
        response = authenticated_management_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Create a new online lesson (rates auto-set in Lesson.save() when None)
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            duration=Decimal("1.0"),
            lesson_type="online",
            teacher_rate=None,  # Explicitly None to trigger auto-set
            student_rate=None,  # Explicitly None to trigger auto-set
            status="completed"
        )

        # Lesson.save() should have set teacher_rate to new global rate
        assert lesson.teacher_rate == Decimal("50.00")
        assert lesson.student_rate == Decimal("60.00")  # Unchanged

    def test_new_inperson_lesson_uses_updated_teacher_rate(
        self, authenticated_management_client, teacher_user, student_user
    ):
        """New in-person lessons use the updated teacher hourly rate."""
        # Update teacher hourly rate
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        data = {'hourly_rate': '100.00'}
        response = authenticated_management_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Refresh teacher data
        teacher_user.refresh_from_db()

        # Create a new in-person lesson (rates auto-set in Lesson.save() when None)
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            duration=Decimal("1.0"),
            lesson_type="in_person",
            teacher_rate=None,  # Explicitly None to trigger auto-set
            student_rate=None,  # Explicitly None to trigger auto-set
            status="completed"
        )

        # Lesson.save() should have set teacher_rate to teacher's new hourly_rate
        assert lesson.teacher_rate == Decimal("100.00")
