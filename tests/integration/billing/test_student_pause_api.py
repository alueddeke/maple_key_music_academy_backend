"""
Integration tests for student pause/resume lesson endpoint.

Endpoint: POST /api/billing/management/students/<student_id>/pause/
Body: { pause_start: "YYYY-MM-DD", pause_end: "YYYY-MM-DD" | null }

Covers:
- POST pause sets window on ALL of a student's schedules (D-02)
- POST with null/null clears (resumes) all schedules
- POST with pause_end < pause_start returns 400
- Cross-school student_id returns 404 (IDOR-safe, T-26-02)
- Teacher/unauthenticated callers rejected (T-26-01)
"""

import pytest
from datetime import date
from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from billing.models import RecurringLessonsSchedule, SchoolSettings

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def authenticated_management_client(api_client, management_user):
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.fixture
def authenticated_teacher_client(api_client, teacher_user):
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def school_settings_fixture(school):
    return SchoolSettings.objects.get_or_create(
        school=school,
        defaults={
            'online_teacher_rate': Decimal('45.00'),
            'online_student_rate': Decimal('60.00'),
            'inperson_student_rate': Decimal('100.00'),
        }
    )[0]


@pytest.fixture
def student_with_schedules(school, teacher_user, school_settings_fixture, db):
    """A student with two Wednesday recurring schedules."""
    student = User.objects.create_user(
        email="pausetest_student@test.com",
        password="testpass123",
        user_type="student",
        first_name="Pause",
        last_name="TestStudent",
        school=school,
        is_approved=True,
    )
    # Schedule 1: Wednesday at 15:00
    RecurringLessonsSchedule.objects.create(
        teacher=teacher_user,
        student=student,
        school=school,
        day_of_week=2,
        start_time="15:00",
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=Decimal("50.00"),
        student_rate=Decimal("100.00"),
        is_active=True,
        start_date=date(2026, 1, 7),
        created_by=teacher_user,
    )
    # Schedule 2: Friday at 10:00
    RecurringLessonsSchedule.objects.create(
        teacher=teacher_user,
        student=student,
        school=school,
        day_of_week=4,
        start_time="10:00",
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=Decimal("50.00"),
        student_rate=Decimal("100.00"),
        is_active=True,
        start_date=date(2026, 1, 7),
        created_by=teacher_user,
    )
    return student


@pytest.fixture
def student_in_second_school(second_school, db):
    """A student in a different school for IDOR testing."""
    SchoolSettings.objects.get_or_create(
        school=second_school,
        defaults={
            'online_teacher_rate': Decimal('40.00'),
            'online_student_rate': Decimal('55.00'),
            'inperson_student_rate': Decimal('90.00'),
        }
    )
    return User.objects.create_user(
        email="other_school_student@test.com",
        password="testpass123",
        user_type="student",
        first_name="Other",
        last_name="SchoolStudent",
        school=second_school,
        is_approved=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestStudentPauseEndpoint:
    """POST management/students/<id>/pause/ applies/clears pause window."""

    def _url(self, student_id):
        return reverse('student_pause_lessons', args=[student_id])

    def test_pause_sets_window_on_all_schedules(
        self, authenticated_management_client, student_with_schedules
    ):
        """POST with pause_start+pause_end sets the same window on ALL schedules (D-02)."""
        url = self._url(student_with_schedules.id)
        data = {'pause_start': '2026-07-01', 'pause_end': '2026-08-31'}
        response = authenticated_management_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_200_OK
        schedules = RecurringLessonsSchedule.objects.filter(student=student_with_schedules)
        assert schedules.count() == 2
        for sched in schedules:
            assert sched.pause_start == date(2026, 7, 1)
            assert sched.pause_end == date(2026, 8, 31)

    def test_pause_response_includes_updated_schedules(
        self, authenticated_management_client, student_with_schedules
    ):
        """Response body contains the serialized updated schedules."""
        url = self._url(student_with_schedules.id)
        data = {'pause_start': '2026-07-01', 'pause_end': '2026-08-31'}
        response = authenticated_management_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert len(response.data) == 2
        for item in response.data:
            assert item['pause_start'] == '2026-07-01'
            assert item['pause_end'] == '2026-08-31'

    def test_clear_window_resumes_all_schedules(
        self, authenticated_management_client, student_with_schedules
    ):
        """POST with null/null clears pause window on ALL schedules (Resume per D-01)."""
        # First set a pause
        RecurringLessonsSchedule.objects.filter(student=student_with_schedules).update(
            pause_start=date(2026, 7, 1), pause_end=date(2026, 8, 31)
        )

        url = self._url(student_with_schedules.id)
        data = {'pause_start': None, 'pause_end': None}
        response = authenticated_management_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_200_OK
        schedules = RecurringLessonsSchedule.objects.filter(student=student_with_schedules)
        for sched in schedules:
            assert sched.pause_start is None
            assert sched.pause_end is None

    def test_pause_end_before_pause_start_returns_400(
        self, authenticated_management_client, student_with_schedules
    ):
        """pause_end < pause_start is rejected with 400 (T-26-03)."""
        url = self._url(student_with_schedules.id)
        data = {'pause_start': '2026-08-31', 'pause_end': '2026-07-01'}
        response = authenticated_management_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data or 'pause_end' in str(response.data).lower()

    def test_cross_school_student_returns_404(
        self, authenticated_management_client, student_in_second_school
    ):
        """Management from school A cannot pause student from school B (T-26-02 / IDOR)."""
        url = self._url(student_in_second_school.id)
        data = {'pause_start': '2026-07-01', 'pause_end': '2026-08-31'}
        response = authenticated_management_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_404_NOT_FOUND
        # Verify no changes were made
        schedules = RecurringLessonsSchedule.objects.filter(student=student_in_second_school)
        for sched in schedules:
            assert sched.pause_start is None

    def test_unauthenticated_returns_401(self, api_client, student_with_schedules):
        """Unauthenticated caller cannot access endpoint (T-26-01)."""
        url = self._url(student_with_schedules.id)
        data = {'pause_start': '2026-07-01', 'pause_end': '2026-08-31'}
        response = api_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_teacher_caller_rejected(
        self, authenticated_teacher_client, student_with_schedules
    ):
        """Teacher cannot pause student lessons -- management_required (T-26-01)."""
        url = self._url(student_with_schedules.id)
        data = {'pause_start': '2026-07-01', 'pause_end': '2026-08-31'}
        response = authenticated_teacher_client.post(url, data, format='json')

        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_invalid_date_format_returns_400(
        self, authenticated_management_client, student_with_schedules
    ):
        """Non-date string in pause_start returns 400."""
        url = self._url(student_with_schedules.id)
        data = {'pause_start': 'not-a-date', 'pause_end': '2026-08-31'}
        response = authenticated_management_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_pause_start_returns_400(
        self, authenticated_management_client, student_with_schedules
    ):
        """pause_start is required; omitting it returns 400."""
        url = self._url(student_with_schedules.id)
        data = {'pause_end': '2026-08-31'}
        response = authenticated_management_client.post(url, data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
