"""
Integration tests for teacher rate propagation to recurring schedules.

Covers the bug where updating a teacher's hourly_rate did not update
the locked rate on existing RecurringLessonsSchedule records or open
BatchLessonItems, forcing management to delete and recreate schedules.

Two endpoints are tested:
  PATCH /api/billing/management/teachers/<pk>/         (rate-only modal)
  PUT   /api/billing/management/teachers/<pk>/update/  (full edit info form)
"""

import pytest
from decimal import Decimal
from datetime import date
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


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def management_client(api_client, management_user):
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.fixture
def student(school, db):
    return User.objects.create_user(
        email="student@ratetest.com",
        password="pass",
        user_type="student",
        first_name="Rate",
        last_name="Student",
        school=school,
        is_approved=True,
    )


@pytest.fixture
def inperson_schedule(teacher_user, student, school, school_settings, db):
    """Active in-person recurring schedule — rate locked at teacher's current hourly_rate."""
    return RecurringLessonsSchedule.objects.create(
        teacher=teacher_user,
        student=student,
        school=school,
        day_of_week=2,  # Wednesday
        start_time="15:00",
        duration=Decimal("1.0"),
        lesson_type="in_person",
        start_date=date(2026, 1, 1),
    )


@pytest.fixture
def online_schedule(teacher_user, student, school, school_settings, db):
    """Active online recurring schedule — rate from school settings, not teacher."""
    return RecurringLessonsSchedule.objects.create(
        teacher=teacher_user,
        student=student,
        school=school,
        day_of_week=3,
        start_time="16:00",
        duration=Decimal("1.0"),
        lesson_type="online",
        start_date=date(2026, 1, 1),
    )


@pytest.fixture
def inactive_schedule(teacher_user, student, school, school_settings, db):
    """Inactive in-person schedule — should never be updated."""
    return RecurringLessonsSchedule.objects.create(
        teacher=teacher_user,
        student=student,
        school=school,
        day_of_week=4,
        start_time="17:00",
        duration=Decimal("1.0"),
        lesson_type="in_person",
        is_active=False,
        start_date=date(2026, 1, 1),
    )


@pytest.fixture
def draft_batch_with_inperson_item(teacher_user, student, school, school_settings, inperson_schedule, db):
    """Draft batch containing an in-person lesson item — should be updated."""
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=school,
        month=4,
        year=2026,
        status="draft",
    )
    BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=date(2026, 4, 2),
        start_time="15:00",
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=teacher_user.hourly_rate,
        student_rate=Decimal("100.00"),
        recurring_schedule=inperson_schedule,
    )
    return batch


@pytest.fixture
def approved_batch_with_item(teacher_user, student, school, school_settings, inperson_schedule, db):
    """Approved batch — teacher_rate on its items must never be touched."""
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=school,
        month=3,
        year=2026,
        status="approved",
    )
    BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=date(2026, 3, 5),
        start_time="15:00",
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=teacher_user.hourly_rate,
        student_rate=Decimal("100.00"),
        recurring_schedule=inperson_schedule,
    )
    return batch


# ---------------------------------------------------------------------------
# PATCH /management/teachers/<pk>/ — dedicated rate modal
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTeacherRateEndpointPropagation:

    def test_rate_update_without_flag_does_not_touch_schedules(
        self, management_client, teacher_user, inperson_schedule
    ):
        """Default behaviour (no flag): schedule rate is unchanged."""
        original_rate = inperson_schedule.teacher_rate
        url = reverse("management_teacher_detail", kwargs={"pk": teacher_user.pk})

        response = management_client.patch(url, {"hourly_rate": "90.00"}, format="json")

        assert response.status_code == status.HTTP_200_OK
        inperson_schedule.refresh_from_db()
        assert inperson_schedule.teacher_rate == original_rate

    def test_rate_update_with_flag_updates_inperson_schedules(
        self, management_client, teacher_user, inperson_schedule
    ):
        """apply_to_schedules=true updates active in-person schedule rates."""
        url = reverse("management_teacher_detail", kwargs={"pk": teacher_user.pk})
        new_rate = Decimal("90.00")

        response = management_client.patch(
            url, {"hourly_rate": str(new_rate), "apply_to_schedules": True}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        inperson_schedule.refresh_from_db()
        assert inperson_schedule.teacher_rate == new_rate

    def test_rate_update_response_includes_schedules_updated_count(
        self, management_client, teacher_user, inperson_schedule
    ):
        """Response body includes schedules_updated count."""
        url = reverse("management_teacher_detail", kwargs={"pk": teacher_user.pk})

        response = management_client.patch(
            url, {"hourly_rate": "90.00", "apply_to_schedules": True}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["schedules_updated"] == 1

    def test_rate_update_does_not_change_online_schedule_rates(
        self, management_client, teacher_user, online_schedule
    ):
        """Online schedule rates come from school settings, not teacher rate."""
        original_rate = online_schedule.teacher_rate
        url = reverse("management_teacher_detail", kwargs={"pk": teacher_user.pk})

        management_client.patch(
            url, {"hourly_rate": "90.00", "apply_to_schedules": True}, format="json"
        )

        online_schedule.refresh_from_db()
        assert online_schedule.teacher_rate == original_rate

    def test_rate_update_does_not_change_inactive_schedule_rates(
        self, management_client, teacher_user, inactive_schedule
    ):
        """Inactive schedules are never updated."""
        original_rate = inactive_schedule.teacher_rate
        url = reverse("management_teacher_detail", kwargs={"pk": teacher_user.pk})

        management_client.patch(
            url, {"hourly_rate": "90.00", "apply_to_schedules": True}, format="json"
        )

        inactive_schedule.refresh_from_db()
        assert inactive_schedule.teacher_rate == original_rate

    def test_rate_update_updates_open_batch_items(
        self, management_client, teacher_user, draft_batch_with_inperson_item
    ):
        """Draft/submitted batch items are updated alongside the schedule."""
        url = reverse("management_teacher_detail", kwargs={"pk": teacher_user.pk})
        new_rate = Decimal("90.00")

        management_client.patch(
            url, {"hourly_rate": str(new_rate), "apply_to_schedules": True}, format="json"
        )

        item = draft_batch_with_inperson_item.lesson_items.first()
        item.refresh_from_db()
        assert item.teacher_rate == new_rate

    def test_rate_update_never_touches_approved_batch_items(
        self, management_client, teacher_user, approved_batch_with_item
    ):
        """Approved batch items are historical records — must not change."""
        item = approved_batch_with_item.lesson_items.first()
        original_rate = item.teacher_rate
        url = reverse("management_teacher_detail", kwargs={"pk": teacher_user.pk})

        management_client.patch(
            url, {"hourly_rate": "90.00", "apply_to_schedules": True}, format="json"
        )

        item.refresh_from_db()
        assert item.teacher_rate == original_rate


# ---------------------------------------------------------------------------
# PUT /management/teachers/<pk>/update/ — full Edit Info form
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestManagementUpdateTeacherPropagation:

    def _base_payload(self, teacher_user):
        return {
            "first_name": teacher_user.first_name,
            "last_name": teacher_user.last_name,
            "email": teacher_user.email,
        }

    def test_edit_info_without_rate_change_returns_zero_schedules_updated(
        self, management_client, teacher_user, inperson_schedule
    ):
        """No rate change → schedules_updated is 0 regardless of flag."""
        url = reverse("management_update_teacher", kwargs={"pk": teacher_user.pk})
        payload = {**self._base_payload(teacher_user), "apply_to_schedules": True}

        response = management_client.put(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["schedules_updated"] == 0

    def test_edit_info_with_rate_change_and_flag_updates_schedules(
        self, management_client, teacher_user, inperson_schedule
    ):
        """Changing hourly_rate via Edit Info with flag propagates to schedules."""
        url = reverse("management_update_teacher", kwargs={"pk": teacher_user.pk})
        new_rate = Decimal("95.00")
        payload = {
            **self._base_payload(teacher_user),
            "hourly_rate": str(new_rate),
            "apply_to_schedules": True,
        }

        response = management_client.put(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["schedules_updated"] == 1
        inperson_schedule.refresh_from_db()
        assert inperson_schedule.teacher_rate == new_rate

    def test_edit_info_with_rate_change_without_flag_does_not_propagate(
        self, management_client, teacher_user, inperson_schedule
    ):
        """Changing rate without flag leaves schedule untouched."""
        original_rate = inperson_schedule.teacher_rate
        url = reverse("management_update_teacher", kwargs={"pk": teacher_user.pk})
        payload = {**self._base_payload(teacher_user), "hourly_rate": "95.00"}

        management_client.put(url, payload, format="json")

        inperson_schedule.refresh_from_db()
        assert inperson_schedule.teacher_rate == original_rate

    def test_edit_info_never_touches_approved_batch_items(
        self, management_client, teacher_user, approved_batch_with_item
    ):
        """Approved batches are immutable regardless of flag or rate change."""
        item = approved_batch_with_item.lesson_items.first()
        original_rate = item.teacher_rate
        url = reverse("management_update_teacher", kwargs={"pk": teacher_user.pk})
        payload = {
            **self._base_payload(teacher_user),
            "hourly_rate": "95.00",
            "apply_to_schedules": True,
        }

        management_client.put(url, payload, format="json")

        item.refresh_from_db()
        assert item.teacher_rate == original_rate
