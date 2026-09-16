"""
Integration tests for interval_weeks on the recurring schedule endpoints (MAP-208).

Endpoints:
  GET/POST  /api/billing/management/students/<student_id>/schedules/
  GET/PUT   /api/billing/management/students/<student_id>/schedules/<schedule_id>/

Covers:
- POST with interval_weeks 2 / omitted (→ 1) / unsupported (→ 400)
- GET list and detail carry interval_weeks + interval_weeks_display
- PUT changes the interval and re-syncs the student's FUTURE, schedule-sourced
  items in OPEN teacher batches (draft/submitted): off-cadence dates removed,
  past items, one-offs and approved batches untouched, switching back re-adds
- The teacher's own batch load does not resurrect what the projection dropped
"""

import pytest
from datetime import date, time, timedelta
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from billing.models import (
    RecurringLessonsSchedule, MonthlyInvoiceBatch, BatchLessonItem,
)

User = get_user_model()

WEDNESDAY = 2
INTERVAL_LABEL = dict(RecurringLessonsSchedule.INTERVAL_CHOICES)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def management_client(management_user):
    client = APIClient()
    client.force_authenticate(user=management_user)
    return client


@pytest.fixture
def teacher_client(teacher_user):
    client = APIClient()
    client.force_authenticate(user=teacher_user)
    return client


@pytest.fixture
def assigned_student(school, teacher_user, school_settings, db):
    """A student assigned to teacher_user (the POST view requires the assignment)."""
    student = User.objects.create_user(
        email="interval_student@test.com",
        password="testpass123",
        user_type="student",
        first_name="Interval",
        last_name="Student",
        school=school,
        is_approved=True,
    )
    student.assigned_teachers.add(teacher_user)
    return student


@pytest.fixture
def weekly_wed_schedule(assigned_student, teacher_user, school):
    """Single weekly Wednesday 15:00 schedule anchored 2026-01-07 (a Wednesday)."""
    return RecurringLessonsSchedule.objects.create(
        teacher=teacher_user,
        student=assigned_student,
        school=school,
        day_of_week=WEDNESDAY,
        start_time="15:00",
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=Decimal("50.00"),
        student_rate=Decimal("100.00"),
        is_active=True,
        start_date=date(2026, 1, 7),
        created_by=teacher_user,
    )


def _list_url(student_id):
    return reverse('student_recurring_schedules', args=[student_id])


def _detail_url(student_id, schedule_id):
    return reverse('recurring_schedule_detail', args=[student_id, schedule_id])


def _create_body(teacher_id, **extra):
    body = {
        'teacher': teacher_id,
        'day_of_week': WEDNESDAY,
        'start_time': '15:00',
        'duration': '1.0',
        'lesson_type': 'in_person',
        'start_date': '2026-01-07',
    }
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Field on create / read / update
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestIntervalWeeksField:

    def test_create_with_interval_two_echoes_value_and_display(
        self, management_client, assigned_student, teacher_user
    ):
        resp = management_client.post(
            _list_url(assigned_student.id),
            _create_body(teacher_user.id, interval_weeks=2), format='json',
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data['interval_weeks'] == 2
        sched = RecurringLessonsSchedule.objects.get(id=resp.data['id'])
        assert sched.interval_weeks == 2
        assert resp.data['interval_weeks_display'] == sched.get_interval_weeks_display()
        assert resp.data['interval_weeks_display'] == INTERVAL_LABEL[2]

    def test_create_without_interval_defaults_to_weekly(
        self, management_client, assigned_student, teacher_user
    ):
        resp = management_client.post(
            _list_url(assigned_student.id), _create_body(teacher_user.id), format='json',
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data['interval_weeks'] == 1
        assert resp.data['interval_weeks_display'] == INTERVAL_LABEL[1]
        assert RecurringLessonsSchedule.objects.get(id=resp.data['id']).interval_weeks == 1

    @pytest.mark.parametrize('unsupported', [0, 3])
    def test_create_with_unsupported_interval_is_rejected(
        self, management_client, assigned_student, teacher_user, unsupported
    ):
        resp = management_client.post(
            _list_url(assigned_student.id),
            _create_body(teacher_user.id, interval_weeks=unsupported), format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'interval_weeks' in resp.data
        assert not RecurringLessonsSchedule.objects.filter(student=assigned_student).exists()

    def test_list_and_detail_carry_interval_fields(
        self, management_client, assigned_student, weekly_wed_schedule
    ):
        weekly_wed_schedule.interval_weeks = 2
        weekly_wed_schedule.save(update_fields=['interval_weeks'])

        listed = management_client.get(_list_url(assigned_student.id))
        assert listed.status_code == status.HTTP_200_OK
        assert [s['interval_weeks'] for s in listed.data] == [2]
        assert listed.data[0]['interval_weeks_display'] == INTERVAL_LABEL[2]

        detail = management_client.get(_detail_url(assigned_student.id, weekly_wed_schedule.id))
        assert detail.status_code == status.HTTP_200_OK
        assert detail.data['interval_weeks'] == 2
        assert detail.data['interval_weeks_display'] == INTERVAL_LABEL[2]

    def test_put_changes_interval(
        self, management_client, assigned_student, weekly_wed_schedule
    ):
        resp = management_client.put(
            _detail_url(assigned_student.id, weekly_wed_schedule.id),
            {'interval_weeks': 2}, format='json',
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        assert resp.data['interval_weeks'] == 2
        weekly_wed_schedule.refresh_from_db()
        assert weekly_wed_schedule.interval_weeks == 2

    def test_put_with_unsupported_interval_is_rejected(
        self, management_client, assigned_student, weekly_wed_schedule
    ):
        resp = management_client.put(
            _detail_url(assigned_student.id, weekly_wed_schedule.id),
            {'interval_weeks': 3}, format='json',
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert 'interval_weeks' in resp.data
        weekly_wed_schedule.refresh_from_db()
        assert weekly_wed_schedule.interval_weeks == 1


# ---------------------------------------------------------------------------
# PUT → open teacher batches re-synced (D-B)
# ---------------------------------------------------------------------------

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
    m = month + delta - 1
    return year + m // 12, m % 12 + 1


def _future_month_wednesdays(months_ahead=1):
    """(year, month, [first_wed, second_wed]) of a month strictly in the future.

    ``reconcile_open_batches_for_student`` only touches items dated after the
    real ``date.today()``; the first Wednesday of any month is on the 7th at the
    latest, so both dates are always inside the month.
    """
    today = date.today()
    year, month = _shift_month(today.year, today.month, months_ahead)
    first = date(year, month, 1)
    w1 = first + timedelta(days=(WEDNESDAY - first.weekday()) % 7)
    return year, month, [w1, w1 + timedelta(days=7)]


def _batch_dates(batch, student):
    return set(
        BatchLessonItem.objects.filter(batch=batch, student=student)
        .values_list('scheduled_date', flat=True)
    )


@pytest.mark.django_db
class TestIntervalChangeReconcilesOpenBatches:

    def _switch(self, client, student, sched, interval):
        resp = client.put(_detail_url(student.id, sched.id), {'interval_weeks': interval}, format='json')
        assert resp.status_code == status.HTTP_200_OK, resp.data
        sched.refresh_from_db()
        return resp

    def test_switch_to_biweekly_removes_off_cadence_future_items(
        self, management_client, assigned_student, weekly_wed_schedule, teacher_user, school
    ):
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, assigned_student, weekly_wed_schedule,
                            month, year, 'draft', weds)

        self._switch(management_client, assigned_student, weekly_wed_schedule, 2)

        projected_future = {
            d for d in weekly_wed_schedule.generate_lessons_for_month(year, month)
            if d > date.today()
        }
        remaining = _batch_dates(batch, assigned_student)
        assert remaining == projected_future
        # Two consecutive Wednesdays: exactly one sits on the 2-week cadence.
        assert len(set(weds) & remaining) == 1
        assert len(set(weds) - remaining) == 1

    def test_past_items_are_kept(
        self, management_client, assigned_student, weekly_wed_schedule, teacher_user, school
    ):
        past = date.today() - timedelta(days=14)
        batch = _make_batch(teacher_user, school, assigned_student, weekly_wed_schedule,
                            past.month, past.year, 'draft', [past])

        self._switch(management_client, assigned_student, weekly_wed_schedule, 2)

        assert past in _batch_dates(batch, assigned_student)

    def test_one_off_items_are_kept(
        self, management_client, assigned_student, weekly_wed_schedule, teacher_user, school
    ):
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, assigned_student, weekly_wed_schedule,
                            month, year, 'draft', weds)
        one_off = BatchLessonItem.objects.create(
            batch=batch, student=assigned_student,
            scheduled_date=weds[0] + timedelta(days=1), start_time=time(11, 0),
            duration=Decimal("1.0"), lesson_type="in_person",
            teacher_rate=Decimal("50.00"), student_rate=Decimal("100.00"),
            status="confirmed", recurring_schedule=None, is_one_off=True,
        )

        self._switch(management_client, assigned_student, weekly_wed_schedule, 2)

        assert BatchLessonItem.objects.filter(id=one_off.id).exists()

    def test_approved_batch_is_untouched(
        self, management_client, assigned_student, weekly_wed_schedule, teacher_user, school
    ):
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, assigned_student, weekly_wed_schedule,
                            month, year, 'approved', weds)

        self._switch(management_client, assigned_student, weekly_wed_schedule, 2)

        assert _batch_dates(batch, assigned_student) == set(weds)

    def test_switch_back_to_weekly_readds_removed_dates(
        self, management_client, assigned_student, weekly_wed_schedule, teacher_user, school
    ):
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, assigned_student, weekly_wed_schedule,
                            month, year, 'draft', weds)

        self._switch(management_client, assigned_student, weekly_wed_schedule, 2)
        assert set(weds) - _batch_dates(batch, assigned_student)  # one removed

        self._switch(management_client, assigned_student, weekly_wed_schedule, 1)
        assert set(weds) <= _batch_dates(batch, assigned_student)

    def test_teacher_batch_load_does_not_resurrect_removed_dates(
        self, management_client, teacher_client, assigned_student, weekly_wed_schedule,
        teacher_user, school
    ):
        year, month, weds = _future_month_wednesdays()
        batch = _make_batch(teacher_user, school, assigned_student, weekly_wed_schedule,
                            month, year, 'draft', weds)

        self._switch(management_client, assigned_student, weekly_wed_schedule, 2)
        removed = set(weds) - _batch_dates(batch, assigned_student)
        assert len(removed) == 1

        # The teacher's batch load runs the schedule sync (add-only).
        resp = teacher_client.post(
            reverse('teacher_monthly_batches'), {'month': month, 'year': year}, format='json',
        )
        assert resp.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), resp.data
        assert removed.isdisjoint(_batch_dates(batch, assigned_student))
