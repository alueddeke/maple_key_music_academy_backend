"""
Integration tests for date field serialization in batch invoice endpoints.

The timezone off-by-one bug: new Date("2026-04-29") in JavaScript treats
the string as UTC midnight, which shifts to the previous day in negative
UTC offset timezones (e.g. EDT = UTC-4). The fix is a frontend-only change,
but these tests pin the backend contract the fix depends on:

  BatchLessonItem.scheduled_date must be serialized as a plain date string
  "YYYY-MM-DD", never as a datetime string like "2026-04-29T00:00:00Z".

If the backend ever changes to returning datetime strings, the frontend
fix would break and the one-day offset would return.
"""

import pytest
from decimal import Decimal
from datetime import date, time
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

from billing.models import (
    RecurringLessonsSchedule,
    MonthlyInvoiceBatch,
    BatchLessonItem,
)

User = get_user_model()

DATE_FORMAT_DESCRIPTION = (
    "Must be YYYY-MM-DD plain date string. "
    "Datetime strings (e.g. '2026-04-29T00:00:00Z') cause a one-day offset "
    "in negative UTC offset timezones (EDT/EST) due to JavaScript Date parsing."
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def management_client(api_client, management_user):
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.fixture
def teacher_client(api_client, teacher_user):
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def student(school, db):
    return User.objects.create_user(
        email="student@datetest.com",
        password="pass",
        user_type="student",
        first_name="Date",
        last_name="Student",
        school=school,
        is_approved=True,
    )


@pytest.fixture
def schedule(teacher_user, student, school, school_settings, db):
    return RecurringLessonsSchedule.objects.create(
        teacher=teacher_user,
        student=student,
        school=school,
        day_of_week=2,
        start_time="15:00",
        duration=Decimal("1.0"),
        lesson_type="in_person",
        start_date=date(2026, 1, 1),
    )


@pytest.fixture
def batch_with_items(teacher_user, student, school, schedule, db):
    """A submitted batch with two lesson items on different known dates."""
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=school,
        month=4,
        year=2026,
        status="submitted",
    )
    BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=date(2026, 4, 29),   # Wednesday 29th — the date from the bug report
        start_time=time(15, 0),
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=Decimal("80.00"),
        student_rate=Decimal("100.00"),
        recurring_schedule=schedule,
    )
    BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=date(2026, 4, 1),    # First of month — edge case
        start_time=time(15, 0),
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=Decimal("80.00"),
        student_rate=Decimal("100.00"),
        recurring_schedule=schedule,
    )
    return batch


@pytest.mark.django_db
class TestBatchLessonDateSerialization:
    """
    Pins the backend date serialization contract that the frontend timezone
    fix depends on. These tests will catch any regression where dates are
    returned as datetime strings instead of plain date strings.
    """

    def test_teacher_batch_detail_returns_plain_date_strings(
        self, teacher_client, batch_with_items, teacher_user
    ):
        """Teacher batch detail: scheduled_date is YYYY-MM-DD, not a datetime."""
        url = reverse("batch_detail", kwargs={"batch_id": batch_with_items.pk})
        response = teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        items = response.data.get("lesson_items", [])
        assert len(items) > 0, "Batch must have lesson items"

        for item in items:
            scheduled_date = item["scheduled_date"]
            assert "T" not in scheduled_date, (
                f"scheduled_date '{scheduled_date}' contains 'T' — "
                f"this is a datetime string, not a date string. {DATE_FORMAT_DESCRIPTION}"
            )
            assert "Z" not in scheduled_date, (
                f"scheduled_date '{scheduled_date}' contains 'Z' — "
                f"this is a UTC datetime string. {DATE_FORMAT_DESCRIPTION}"
            )
            # Confirm it's exactly YYYY-MM-DD
            parts = scheduled_date.split("-")
            assert len(parts) == 3, f"Expected YYYY-MM-DD, got '{scheduled_date}'"
            assert len(parts[0]) == 4  # year
            assert len(parts[1]) == 2  # month
            assert len(parts[2]) == 2  # day

    def test_teacher_batch_detail_preserves_exact_date_values(
        self, teacher_client, batch_with_items
    ):
        """The exact date stored is the exact date returned — no UTC shift."""
        url = reverse("batch_detail", kwargs={"batch_id": batch_with_items.pk})
        response = teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        returned_dates = {item["scheduled_date"] for item in response.data["lesson_items"]}

        assert "2026-04-29" in returned_dates, (
            "2026-04-29 (the date from the bug report) was not returned correctly. "
            f"Got: {returned_dates}"
        )
        assert "2026-04-01" in returned_dates

    def test_management_batch_detail_returns_plain_date_strings(
        self, management_client, batch_with_items
    ):
        """Management batch review: scheduled_date is also YYYY-MM-DD."""
        url = reverse("management_batch_detail", kwargs={"batch_id": batch_with_items.pk})
        response = management_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        items = response.data.get("lesson_items", [])
        assert len(items) > 0

        for item in items:
            scheduled_date = item["scheduled_date"]
            assert "T" not in scheduled_date, (
                f"Management view returned datetime string '{scheduled_date}'. "
                f"{DATE_FORMAT_DESCRIPTION}"
            )

    def test_management_batch_detail_preserves_exact_date_values(
        self, management_client, batch_with_items
    ):
        """Management view returns the same exact dates as stored."""
        url = reverse("management_batch_detail", kwargs={"batch_id": batch_with_items.pk})
        response = management_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        returned_dates = {item["scheduled_date"] for item in response.data["lesson_items"]}

        assert "2026-04-29" in returned_dates, (
            f"Expected 2026-04-29, got {returned_dates}"
        )
        assert "2026-04-01" in returned_dates


@pytest.mark.django_db
class TestRecurringScheduleDateSerialization:
    """
    Pins date serialization for recurring schedule start/end dates.
    These feed into the student management view which previously had
    the same bug (fixed in commit f12edfd).
    """

    def test_schedule_start_date_is_plain_date_string(
        self, management_client, teacher_user, schedule
    ):
        """start_date on recurring schedules is returned as YYYY-MM-DD."""
        url = reverse(
            "student_recurring_schedules",
            kwargs={"student_id": schedule.student.pk},
        )
        response = management_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) > 0

        start_date = response.data[0]["start_date"]
        assert "T" not in start_date, (
            f"start_date '{start_date}' is a datetime string. {DATE_FORMAT_DESCRIPTION}"
        )
        assert start_date == "2026-01-01"
