"""
MAP-284: management records one trial lesson per student, independent of any
recurring schedule.

Route: /api/billing/management/students/<student_id>/trial-lesson/ (GET, POST, DELETE)

Covers every Acceptance bullet of the ticket that is backend-testable:
  - POST with no history -> 201, trial item with recurring_schedule=None in the
    teacher's draft batch for that month (batch created when missing), student
    charge is 0, student_rate snapshot comes from resolve_rates.
  - Trial first, then schedule + sync -> schedule's first item is confirmed,
    exactly one trial item.
  - Schedule synced first, then POST -> the auto-trial item is demoted to
    confirmed, exactly one trial item.
  - 400 bodies: teacher not assigned, month already approved, second trial.
  - 404 for a cross-school student.
  - DELETE on draft -> 204; after approval -> 409.
  - Approving the batch creates Lesson(is_trial=True, status='trial',
    student_rate=0), no StudentInvoice, teacher payment for the item is rate x duration.
  - A schedule PUT / pause (reconcile_open_batches_for_student) leaves the
    schedule-less trial item alone.
"""
from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from billing.models import (
    BatchLessonItem,
    BillableContact,
    Lesson,
    MonthlyInvoiceBatch,
    RecurringLessonsSchedule,
    StudentInvoice,
)
from billing.services.rates import resolve_rates

User = get_user_model()


def _future_month(months_ahead=2):
    """(year, month) a couple of months out so every date in it is > today."""
    today = date.today()
    month = today.month + months_ahead
    year = today.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return year, month


def _date_in(year, month, day):
    return date(year, month, day)


def _weekday_on_or_after(d, weekday):
    """First date >= d whose weekday() == weekday."""
    return d + timedelta(days=(weekday - d.weekday()) % 7)


@pytest.fixture
def management_client(api_client, management_user):
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.fixture
def teacher_client(teacher_user):
    client = APIClient()
    client.force_authenticate(user=teacher_user)
    return client


@pytest.fixture
def new_student(school, teacher_user, school_settings, db):
    """Student with zero Lesson / BatchLessonItem history, assigned to teacher_user,
    with a complete primary billable contact so a batch can be approved."""
    student = User.objects.create_user(
        email="trial.student@test.com",
        password="testpass123",
        user_type="student",
        first_name="Trial",
        last_name="Student",
        school=school,
        is_approved=True,
    )
    student.assigned_teachers.add(teacher_user)
    BillableContact.objects.create(
        student=student,
        school=school,
        is_primary=True,
        first_name="Trial",
        last_name="Parent",
        email="trial.parent@test.com",
        phone="555-0100",
        street_address="1 Trial St",
        city="Toronto",
        province="ON",
        postal_code="M5H 2N2",
    )
    return student


@pytest.fixture
def other_teacher(school, db):
    return User.objects.create_user(
        email="other.teacher@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Other",
        last_name="Teacher",
        hourly_rate=Decimal("70.00"),
        school=school,
        is_approved=True,
    )


def url_for(student):
    return reverse("management_student_trial_lesson", kwargs={"student_id": student.pk})


def post_trial(client, student, teacher, on_date, **overrides):
    body = {
        "teacher": teacher.pk,
        "date": on_date.isoformat(),
        "start_time": "16:00:00",
        "duration": "1.00",
        "lesson_type": "in_person",
    }
    body.update(overrides)
    return client.post(url_for(student), body, format="json")


def sync_batch(teacher_client, year, month):
    resp = teacher_client.post(
        reverse("teacher_monthly_batches"), {"month": month, "year": year}, format="json"
    )
    assert resp.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), resp.content
    return MonthlyInvoiceBatch.objects.get(id=resp.data["id"])


@pytest.mark.django_db
class TestCreateTrialLesson:

    def test_post_creates_trial_item_and_draft_batch(
        self, management_client, new_student, teacher_user, school
    ):
        year, month = _future_month()
        on_date = _date_in(year, month, 5)
        assert not MonthlyInvoiceBatch.objects.filter(teacher=teacher_user).exists()

        resp = post_trial(management_client, new_student, teacher_user, on_date)

        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        batch = MonthlyInvoiceBatch.objects.get(
            teacher=teacher_user, school=school, month=month, year=year
        )
        assert batch.status == "draft"
        item = BatchLessonItem.objects.get(student=new_student)
        assert item.batch_id == batch.id
        assert item.status == "trial"
        assert item.recurring_schedule is None
        assert item.is_one_off is False
        assert item.scheduled_date == on_date
        assert item.start_time == time(16, 0)
        assert item.duration == Decimal("1.00")

        teacher_rate, student_rate = resolve_rates(school, teacher_user, "in_person")
        assert item.teacher_rate == teacher_rate
        assert item.student_rate == student_rate
        assert item.calculate_student_charge() == Decimal("0.00")
        assert item.calculate_teacher_payment() == teacher_rate * item.duration

        assert resp.data["id"] == item.id
        assert resp.data["batch_id"] == batch.id
        assert resp.data["batch_status"] == "draft"
        assert resp.data["status"] == "trial"
        assert Decimal(resp.data["student_charge"]) == Decimal("0.00")

    def test_post_reuses_existing_draft_batch(
        self, management_client, new_student, teacher_user, school
    ):
        year, month = _future_month()
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=month, year=year, status="draft"
        )

        resp = post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5))

        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        assert MonthlyInvoiceBatch.objects.filter(teacher=teacher_user).count() == 1
        assert resp.data["batch_id"] == batch.id

    def test_lesson_type_defaults_to_in_person_and_online_uses_online_rates(
        self, management_client, new_student, teacher_user, school
    ):
        year, month = _future_month()
        resp = post_trial(
            management_client, new_student, teacher_user, _date_in(year, month, 5),
            lesson_type="online",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        item = BatchLessonItem.objects.get(student=new_student)
        assert item.lesson_type == "online"
        teacher_rate, student_rate = resolve_rates(school, teacher_user, "online")
        assert (item.teacher_rate, item.student_rate) == (teacher_rate, student_rate)

    def test_post_without_lesson_type_defaults_in_person(
        self, management_client, new_student, teacher_user, school
    ):
        year, month = _future_month()
        body = {
            "teacher": teacher_user.pk,
            "date": _date_in(year, month, 5).isoformat(),
            "start_time": "16:00:00",
            "duration": "0.50",
        }
        resp = management_client.post(url_for(new_student), body, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        assert BatchLessonItem.objects.get(student=new_student).lesson_type == "in_person"

    def test_any_weekday_is_accepted(self, management_client, new_student, teacher_user):
        """No day_of_week restriction: the trial can land on a day no schedule uses."""
        year, month = _future_month()
        for day in range(1, 8):
            on_date = _date_in(year, month, day)
            resp = post_trial(management_client, new_student, teacher_user, on_date)
            assert resp.status_code == status.HTTP_201_CREATED, (day, resp.content)
            management_client.delete(url_for(new_student))


@pytest.mark.django_db
class TestTrialAndScheduleInteraction:

    def test_trial_first_then_schedule_sync_first_schedule_item_is_confirmed(
        self, management_client, teacher_client, new_student, teacher_user, school
    ):
        year, month = _future_month()
        trial_date = _date_in(year, month, 2)
        resp = post_trial(management_client, new_student, teacher_user, trial_date)
        assert resp.status_code == status.HTTP_201_CREATED, resp.content

        # Schedule starts >= 7 days later on a different weekday.
        start = _weekday_on_or_after(trial_date + timedelta(days=7), (trial_date.weekday() + 1) % 7)
        RecurringLessonsSchedule.objects.create(
            teacher=teacher_user, student=new_student, school=school,
            day_of_week=start.weekday(), start_time=time(15, 0),
            duration=Decimal("1.00"), lesson_type="in_person",
            start_date=start, is_active=True,
        )
        batch = sync_batch(teacher_client, year, month)

        items = BatchLessonItem.objects.filter(student=new_student, batch=batch)
        trial_items = items.filter(status="trial")
        assert trial_items.count() == 1
        assert trial_items.get().scheduled_date == trial_date
        assert trial_items.get().recurring_schedule is None
        schedule_items = items.filter(recurring_schedule__isnull=False).order_by("scheduled_date")
        assert schedule_items.exists()
        assert schedule_items.first().scheduled_date == start
        assert set(schedule_items.values_list("status", flat=True)) == {"confirmed"}

    def test_schedule_synced_first_then_post_demotes_auto_trial(
        self, management_client, teacher_client, new_student, teacher_user, school
    ):
        year, month = _future_month()
        start = _date_in(year, month, 10)
        RecurringLessonsSchedule.objects.create(
            teacher=teacher_user, student=new_student, school=school,
            day_of_week=start.weekday(), start_time=time(15, 0),
            duration=Decimal("1.00"), lesson_type="in_person",
            start_date=start, is_active=True,
        )
        batch = sync_batch(teacher_client, year, month)
        auto_trial = BatchLessonItem.objects.get(student=new_student, status="trial")
        assert auto_trial.recurring_schedule is not None

        trial_date = _date_in(year, month, 2)
        resp = post_trial(management_client, new_student, teacher_user, trial_date)
        assert resp.status_code == status.HTTP_201_CREATED, resp.content

        auto_trial.refresh_from_db()
        assert auto_trial.status == "confirmed"
        trial_items = BatchLessonItem.objects.filter(student=new_student, status="trial")
        assert trial_items.count() == 1
        assert trial_items.get().scheduled_date == trial_date
        assert trial_items.get().batch_id == batch.id

    def test_pause_reconcile_leaves_trial_item_alone(
        self, management_client, teacher_client, new_student, teacher_user, school
    ):
        """reconcile_open_batches_for_student only deletes schedule-sourced items."""
        year, month = _future_month()
        trial_date = _date_in(year, month, 2)
        assert post_trial(management_client, new_student, teacher_user, trial_date).status_code == 201
        start = _date_in(year, month, 10)
        RecurringLessonsSchedule.objects.create(
            teacher=teacher_user, student=new_student, school=school,
            day_of_week=start.weekday(), start_time=time(15, 0),
            duration=Decimal("1.00"), lesson_type="in_person",
            start_date=start, is_active=True,
        )
        sync_batch(teacher_client, year, month)
        assert BatchLessonItem.objects.filter(student=new_student, recurring_schedule__isnull=False).exists()

        # Open-ended pause from the 1st of the month: every schedule item goes away.
        resp = management_client.post(
            reverse("student_pause_lessons", kwargs={"student_id": new_student.pk}),
            {"pause_start": _date_in(year, month, 1).isoformat(), "pause_end": None},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.content

        assert not BatchLessonItem.objects.filter(student=new_student, recurring_schedule__isnull=False).exists()
        trial = BatchLessonItem.objects.get(student=new_student)
        assert trial.status == "trial"
        assert trial.scheduled_date == trial_date


@pytest.mark.django_db
class TestCreateValidation:

    def test_teacher_not_assigned(self, management_client, new_student, other_teacher):
        year, month = _future_month()
        resp = post_trial(management_client, new_student, other_teacher, _date_in(year, month, 5))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json() == {"error": "teacher is not assigned to this student"}
        assert not BatchLessonItem.objects.filter(student=new_student).exists()

    def test_teacher_from_other_school(
        self, management_client, new_student, second_school, second_school_settings
    ):
        foreign = User.objects.create_user(
            email="foreign.teacher@test.com", password="x", user_type="teacher",
            first_name="F", last_name="T", hourly_rate=Decimal("60.00"),
            school=second_school, is_approved=True,
        )
        new_student.assigned_teachers.add(foreign)
        year, month = _future_month()
        resp = post_trial(management_client, new_student, foreign, _date_in(year, month, 5))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json() == {"error": "teacher is not assigned to this student"}

    def test_month_already_approved(self, management_client, new_student, teacher_user, school):
        year, month = _future_month()
        MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=month, year=year, status="approved"
        )
        resp = post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json() == {"error": "that month is already approved for this teacher"}

    def test_second_trial_rejected(self, management_client, new_student, teacher_user):
        year, month = _future_month()
        assert post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5)).status_code == 201
        resp = post_trial(management_client, new_student, teacher_user, _date_in(year, month, 12))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json() == {"error": "student already has a trial lesson"}
        assert BatchLessonItem.objects.filter(student=new_student).count() == 1

    def test_student_with_trial_lesson_row_rejected(
        self, management_client, new_student, teacher_user, school
    ):
        Lesson.objects.create(
            teacher=teacher_user, student=new_student, school=school,
            lesson_type="in_person", is_trial=True,
            scheduled_date=date.today() - timedelta(days=30),
            duration=Decimal("1.00"), status="completed",
        )
        year, month = _future_month()
        resp = post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json() == {"error": "student already has a trial lesson"}

    def test_wrong_school_student_404(
        self, management_client, teacher_user, second_school, second_school_settings
    ):
        foreign_student = User.objects.create_user(
            email="foreign.student@test.com", password="x", user_type="student",
            first_name="F", last_name="S", school=second_school, is_approved=True,
        )
        year, month = _future_month()
        resp = post_trial(management_client, foreign_student, teacher_user, _date_in(year, month, 5))
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert management_client.get(url_for(foreign_student)).status_code == status.HTTP_404_NOT_FOUND
        assert management_client.delete(url_for(foreign_student)).status_code == status.HTTP_404_NOT_FOUND

    def test_missing_fields_400(self, management_client, new_student, teacher_user):
        resp = management_client.post(url_for(new_student), {"teacher": teacher_user.pk}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert {"date", "start_time", "duration"} <= set(resp.json().keys())

    def test_unknown_field_400(self, management_client, new_student, teacher_user):
        year, month = _future_month()
        resp = post_trial(
            management_client, new_student, teacher_user, _date_in(year, month, 5), student_rate="0.00"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["error"] == ["unknown_fields"]

    def test_zero_duration_400(self, management_client, new_student, teacher_user):
        year, month = _future_month()
        resp = post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5), duration="0")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "duration" in resp.json()

    def test_teacher_role_forbidden(self, teacher_client, new_student, teacher_user):
        year, month = _future_month()
        resp = post_trial(teacher_client, new_student, teacher_user, _date_in(year, month, 5))
        assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestGetAndDelete:

    def test_get_404_when_no_trial(self, management_client, new_student):
        assert management_client.get(url_for(new_student)).status_code == status.HTTP_404_NOT_FOUND

    def test_get_returns_trial_with_batch_fields(self, management_client, new_student, teacher_user):
        year, month = _future_month()
        created = post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5))
        resp = management_client.get(url_for(new_student))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == created.json()
        assert resp.data["batch_status"] == "draft"

    def test_delete_on_draft_204(self, management_client, new_student, teacher_user):
        year, month = _future_month()
        post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5))
        resp = management_client.delete(url_for(new_student))
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not BatchLessonItem.objects.filter(student=new_student).exists()
        assert management_client.get(url_for(new_student)).status_code == status.HTTP_404_NOT_FOUND

    def test_delete_404_when_no_trial(self, management_client, new_student):
        assert management_client.delete(url_for(new_student)).status_code == status.HTTP_404_NOT_FOUND

    def test_delete_after_submit_409(self, management_client, new_student, teacher_user):
        year, month = _future_month()
        resp = post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5))
        batch = MonthlyInvoiceBatch.objects.get(id=resp.data["batch_id"])
        batch.status = "submitted"
        batch.save(update_fields=["status"])
        resp = management_client.delete(url_for(new_student))
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.json() == {"error": "trial lesson can no longer be removed"}
        assert BatchLessonItem.objects.filter(student=new_student).count() == 1

    def test_delete_after_approval_409(self, management_client, new_student, teacher_user):
        year, month = _future_month()
        resp = post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5))
        batch = MonthlyInvoiceBatch.objects.get(id=resp.data["batch_id"])
        batch.status = "submitted"
        batch.save(update_fields=["status"])
        approve = management_client.post(
            reverse("management_approve_batch", kwargs={"batch_id": batch.pk}), format="json"
        )
        assert approve.status_code == status.HTTP_200_OK, approve.content
        resp = management_client.delete(url_for(new_student))
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert resp.json() == {"error": "trial lesson can no longer be removed"}

    def test_delete_auto_detected_schedule_trial_409(
        self, management_client, teacher_client, new_student, teacher_user, school
    ):
        """Only the explicit (schedule-less) trial is removable through this route."""
        year, month = _future_month()
        start = _date_in(year, month, 10)
        RecurringLessonsSchedule.objects.create(
            teacher=teacher_user, student=new_student, school=school,
            day_of_week=start.weekday(), start_time=time(15, 0),
            duration=Decimal("1.00"), lesson_type="in_person",
            start_date=start, is_active=True,
        )
        sync_batch(teacher_client, year, month)
        resp = management_client.delete(url_for(new_student))
        assert resp.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
class TestApproval:

    def test_approving_batch_with_explicit_trial(
        self, management_client, new_student, teacher_user, school
    ):
        year, month = _future_month()
        resp = post_trial(management_client, new_student, teacher_user, _date_in(year, month, 5))
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        batch = MonthlyInvoiceBatch.objects.get(id=resp.data["batch_id"])
        item = batch.lesson_items.get()
        teacher_rate, _ = resolve_rates(school, teacher_user, "in_person")
        assert item.calculate_teacher_payment() == teacher_rate * item.duration

        batch.status = "submitted"
        batch.save(update_fields=["status"])
        approve = management_client.post(
            reverse("management_approve_batch", kwargs={"batch_id": batch.pk}), format="json"
        )
        assert approve.status_code == status.HTTP_200_OK, approve.content

        lesson = Lesson.objects.get(student=new_student)
        assert lesson.is_trial is True
        assert lesson.status == "trial"
        assert lesson.student_rate == Decimal("0.00")
        assert lesson.teacher_rate == teacher_rate
        assert lesson.scheduled_date.date() == _date_in(year, month, 5)
        assert StudentInvoice.objects.filter(student=new_student).count() == 0
        batch.refresh_from_db()
        assert batch.status == "approved"
