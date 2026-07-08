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

import calendar
import pytest
from datetime import date, time, timedelta
from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from billing.models import (
    RecurringLessonsSchedule, SchoolSettings,
    MonthlyInvoiceBatch, BatchLessonItem,
)

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


# ---------------------------------------------------------------------------
# Cascade to open teacher batches — pause reflected on teacher invoices
# ---------------------------------------------------------------------------

@pytest.fixture
def student_one_wed_schedule(school, teacher_user, school_settings_fixture, db):
    """Student with a SINGLE Wednesday 15:00 recurring schedule (deterministic)."""
    student = User.objects.create_user(
        email="cascade_student@test.com",
        password="testpass123",
        user_type="student",
        first_name="Cascade",
        last_name="Student",
        school=school,
        is_approved=True,
    )
    sched = RecurringLessonsSchedule.objects.create(
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
    return student, sched


def _make_batch(teacher, school, student, sched, month, year, status_value, dates):
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher, school=school, month=month, year=year, status=status_value,
    )
    for d in dates:
        BatchLessonItem.objects.create(
            batch=batch, student=student, scheduled_date=d, start_time=time(15, 0),
            duration=Decimal("1.0"), lesson_type="in_person",
            teacher_rate=Decimal("50.00"), student_rate=Decimal("100.00"),
            status="confirmed", recurring_schedule=sched, is_one_off=False,
        )
    return batch


def _shift_month(year, month, delta):
    """Return (year, month) shifted forward by ``delta`` months."""
    m = month + delta - 1
    return year + m // 12, m % 12 + 1


def _future_month_wednesdays(months_ahead=1):
    """(year, month, [first_wed, second_wed]) of a month ``months_ahead``
    months after the real current month.

    The reconcile boundary is ``scheduled_date > date.today()`` (real clock),
    so these tests must use dates that are strictly future on ANY run date.
    The first Wednesday of a month falls on the 7th at the latest, so both
    returned Wednesdays are always within the month.
    """
    today = date.today()
    year, month = _shift_month(today.year, today.month, months_ahead)
    first = date(year, month, 1)
    w1 = first + timedelta(days=(2 - first.weekday()) % 7)  # day_of_week=2 (Wed)
    return year, month, [w1, w1 + timedelta(days=7)]


def _month_bounds_iso(year, month):
    """('YYYY-MM-01', 'YYYY-MM-<last>') pause window covering a whole month."""
    last = calendar.monthrange(year, month)[1]
    return (
        date(year, month, 1).isoformat(),
        date(year, month, last).isoformat(),
    )


@pytest.mark.django_db
class TestPauseCascadeToOpenBatches:
    """Pausing a student removes future in-window lessons from open teacher batches.

    ``reconcile_open_batches_for_student`` only touches items strictly after
    the real ``date.today()``, so all batch dates here are computed relative
    to the run date (next month's Wednesdays) instead of hardcoded. Boundaries:
    only draft/submitted batches, only future schedule-sourced items (T-26-10).
    """

    def _url(self, student_id):
        return reverse('student_pause_lessons', args=[student_id])

    def _dates(self, batch, student):
        return set(
            BatchLessonItem.objects.filter(batch=batch, student=student)
            .values_list('scheduled_date', flat=True)
        )

    def test_pause_removes_future_in_window_items_from_draft(
        self, authenticated_management_client, student_one_wed_schedule, teacher_user, school
    ):
        student, sched = student_one_wed_schedule
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, student, sched, month, year, 'draft', weds)
        pause_start, pause_end = _month_bounds_iso(year, month)
        resp = authenticated_management_client.post(
            self._url(student.id),
            {'pause_start': pause_start, 'pause_end': pause_end}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert self._dates(batch, student) == set()  # both future items removed

    def test_pause_keeps_items_outside_window(
        self, authenticated_management_client, student_one_wed_schedule, teacher_user, school
    ):
        student, sched = student_one_wed_schedule
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, student, sched, month, year, 'draft',
                            [weds[0]])
        # Pause the FOLLOWING month only -> the batch item is outside the
        # window, must stay.
        next_year, next_month = _shift_month(year, month, 1)
        pause_start, pause_end = _month_bounds_iso(next_year, next_month)
        resp = authenticated_management_client.post(
            self._url(student.id),
            {'pause_start': pause_start, 'pause_end': pause_end}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert weds[0] in self._dates(batch, student)

    def test_pause_keeps_past_items(
        self, authenticated_management_client, student_one_wed_schedule, teacher_user, school
    ):
        student, sched = student_one_wed_schedule
        # Past-dated item (two weeks before the real today), inside an
        # open-ended pause starting at that month's first day.
        past = date.today() - timedelta(days=14)
        batch = _make_batch(teacher_user, school, student, sched,
                            past.month, past.year, 'draft', [past])
        pause_start, _ = _month_bounds_iso(past.year, past.month)
        resp = authenticated_management_client.post(
            self._url(student.id),
            {'pause_start': pause_start, 'pause_end': None}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert past in self._dates(batch, student)  # already happened -> kept

    def test_pause_does_not_touch_approved_batch(
        self, authenticated_management_client, student_one_wed_schedule, teacher_user, school
    ):
        student, sched = student_one_wed_schedule
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, student, sched, month, year, 'approved',
                            [weds[0]])
        pause_start, pause_end = _month_bounds_iso(year, month)
        resp = authenticated_management_client.post(
            self._url(student.id),
            {'pause_start': pause_start, 'pause_end': pause_end}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert weds[0] in self._dates(batch, student)  # locked -> unchanged

    def test_pause_cleans_submitted_batch(
        self, authenticated_management_client, student_one_wed_schedule, teacher_user, school
    ):
        student, sched = student_one_wed_schedule
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, student, sched, month, year, 'submitted',
                            [weds[0]])
        pause_start, pause_end = _month_bounds_iso(year, month)
        resp = authenticated_management_client.post(
            self._url(student.id),
            {'pause_start': pause_start, 'pause_end': pause_end}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert weds[0] not in self._dates(batch, student)

    def test_resume_readds_future_items_to_open_batch(
        self, authenticated_management_client, student_one_wed_schedule, teacher_user, school
    ):
        student, sched = student_one_wed_schedule
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, student, sched, month, year, 'draft', weds)
        pause_start, pause_end = _month_bounds_iso(year, month)
        # Pause removes them...
        authenticated_management_client.post(
            self._url(student.id),
            {'pause_start': pause_start, 'pause_end': pause_end}, format='json')
        assert self._dates(batch, student) == set()
        # ...resume restores the future Wednesdays the schedule projects.
        resp = authenticated_management_client.post(
            self._url(student.id),
            {'pause_start': None, 'pause_end': None}, format='json')
        assert resp.status_code == status.HTTP_200_OK
        restored = self._dates(batch, student)
        assert weds[0] in restored
        assert weds[1] in restored
