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
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

from billing.models import (
    Lesson,
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
    """Active online recurring schedule — teacher has no online override, so the school online rate."""
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
        """An hourly_rate-only PATCH never re-prices online schedules."""
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


# ---------------------------------------------------------------------------
# MAP-163: per-teacher online rate (online_hourly_rate) on the PATCH endpoint
# ---------------------------------------------------------------------------

def _override(school_settings):
    """An online override distinct from the school online rate."""
    return school_settings.online_teacher_rate + Decimal("5.00")


@pytest.fixture
def draft_batch_with_online_item(teacher_user, student, school, school_settings, online_schedule, db):
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user, school=school, month=5, year=2026, status="draft",
    )
    BatchLessonItem.objects.create(
        batch=batch, student=student, scheduled_date=date(2026, 5, 6),
        start_time="16:00", duration=Decimal("1.0"), lesson_type="online",
        teacher_rate=school_settings.online_teacher_rate,
        student_rate=school_settings.online_student_rate,
        recurring_schedule=online_schedule,
    )
    return batch


@pytest.fixture
def approved_batch_with_online_item(teacher_user, student, school, school_settings, online_schedule, db):
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user, school=school, month=2, year=2026, status="approved",
    )
    BatchLessonItem.objects.create(
        batch=batch, student=student, scheduled_date=date(2026, 2, 4),
        start_time="16:00", duration=Decimal("1.0"), lesson_type="online",
        teacher_rate=school_settings.online_teacher_rate,
        student_rate=school_settings.online_student_rate,
        recurring_schedule=online_schedule,
    )
    return batch


@pytest.fixture
def inactive_online_schedule(teacher_user, student, school, school_settings, db):
    return RecurringLessonsSchedule.objects.create(
        teacher=teacher_user, student=student, school=school,
        day_of_week=5, start_time="18:00", duration=Decimal("1.0"),
        lesson_type="online", is_active=False, start_date=date(2026, 1, 1),
    )


@pytest.mark.django_db
class TestOnlineRateEndpoint:

    def _url(self, teacher):
        return reverse("management_teacher_detail", kwargs={"pk": teacher.pk})

    def test_teacher_list_and_detail_expose_online_hourly_rate(
        self, management_client, teacher_user, school_settings
    ):
        list_resp = management_client.get(reverse("management_teacher_list"))
        detail_resp = management_client.get(self._url(teacher_user))

        row = next(t for t in list_resp.data if t["id"] == teacher_user.pk)
        assert row["online_hourly_rate"] is None
        assert detail_resp.data["online_hourly_rate"] is None

        teacher_user.online_hourly_rate = _override(school_settings)
        teacher_user.save()

        detail_resp = management_client.get(self._url(teacher_user))
        assert Decimal(detail_resp.data["online_hourly_rate"]) == teacher_user.online_hourly_rate

    def test_online_rate_set_and_hourly_rate_untouched(
        self, management_client, teacher_user, school_settings
    ):
        original_hourly = teacher_user.hourly_rate
        new_online = _override(school_settings)

        response = management_client.patch(
            self._url(teacher_user), {"online_hourly_rate": str(new_online)}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert Decimal(response.data["online_hourly_rate"]) == new_online
        teacher_user.refresh_from_db()
        assert teacher_user.online_hourly_rate == new_online
        assert teacher_user.hourly_rate == original_hourly

    def test_clearing_online_override_returns_to_school_rate_and_keeps_locked_rows(
        self, management_client, teacher_user, student, school, school_settings
    ):
        teacher_user.online_hourly_rate = _override(school_settings)
        teacher_user.save()
        locked = Lesson.objects.create(
            teacher=teacher_user, student=student, school=school, lesson_type="online",
            is_trial=False, scheduled_date=timezone.now(), duration=1.0, status="confirmed",
        )
        assert locked.teacher_rate == teacher_user.online_hourly_rate

        response = management_client.patch(
            self._url(teacher_user), {"online_hourly_rate": None}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["online_hourly_rate"] is None
        teacher_user.refresh_from_db()
        assert teacher_user.online_hourly_rate is None

        fresh = Lesson.objects.create(
            teacher=teacher_user, student=student, school=school, lesson_type="online",
            is_trial=False, scheduled_date=timezone.now(), duration=1.0, status="confirmed",
        )
        assert fresh.teacher_rate == school_settings.online_teacher_rate
        before = locked.teacher_rate
        locked.refresh_from_db()
        assert locked.teacher_rate == before

    def test_online_rate_negative_400_row_unchanged(
        self, management_client, teacher_user, school_settings
    ):
        teacher_user.online_hourly_rate = _override(school_settings)
        teacher_user.save()

        response = management_client.patch(
            self._url(teacher_user), {"online_hourly_rate": "-1.00"}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert isinstance(response.data["error"], str)
        before = teacher_user.online_hourly_rate
        teacher_user.refresh_from_db()
        assert teacher_user.online_hourly_rate == before

    def test_online_rate_non_numeric_400(self, management_client, teacher_user):
        response = management_client.patch(
            self._url(teacher_user), {"online_hourly_rate": "abc"}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert isinstance(response.data["error"], str)
        teacher_user.refresh_from_db()
        assert teacher_user.online_hourly_rate is None

    def test_patch_without_rate_fields_400(self, management_client, teacher_user):
        response = management_client.patch(
            self._url(teacher_user), {"apply_to_schedules": True}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert isinstance(response.data["error"], str)

    def test_mixed_valid_and_invalid_rates_400_both_unchanged(
        self, management_client, teacher_user
    ):
        original_hourly = teacher_user.hourly_rate

        response = management_client.patch(
            self._url(teacher_user),
            {"hourly_rate": str(original_hourly + Decimal("10.00")), "online_hourly_rate": "-5"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        teacher_user.refresh_from_db()
        assert teacher_user.hourly_rate == original_hourly
        assert teacher_user.online_hourly_rate is None

    def test_online_rate_with_flag_updates_online_schedules_and_open_items(
        self, management_client, teacher_user, school_settings,
        online_schedule, draft_batch_with_online_item,
    ):
        new_online = _override(school_settings)

        response = management_client.patch(
            self._url(teacher_user),
            {"online_hourly_rate": str(new_online), "apply_to_schedules": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["schedules_updated"] == 1
        online_schedule.refresh_from_db()
        assert online_schedule.teacher_rate == new_online
        item = draft_batch_with_online_item.lesson_items.get()
        assert item.teacher_rate == new_online

    def test_online_rate_update_leaves_inperson_inactive_approved_untouched(
        self, management_client, teacher_user, school_settings,
        inperson_schedule, draft_batch_with_inperson_item,
        inactive_online_schedule, approved_batch_with_online_item,
    ):
        inperson_before = inperson_schedule.teacher_rate
        inperson_item = draft_batch_with_inperson_item.lesson_items.get()
        inperson_item_before = inperson_item.teacher_rate
        inactive_before = inactive_online_schedule.teacher_rate
        approved_item = approved_batch_with_online_item.lesson_items.get()
        approved_before = approved_item.teacher_rate

        response = management_client.patch(
            self._url(teacher_user),
            {"online_hourly_rate": str(_override(school_settings)), "apply_to_schedules": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        for obj in (inperson_schedule, inperson_item, inactive_online_schedule, approved_item):
            obj.refresh_from_db()
        assert inperson_schedule.teacher_rate == inperson_before
        assert inperson_item.teacher_rate == inperson_item_before
        assert inactive_online_schedule.teacher_rate == inactive_before
        assert approved_item.teacher_rate == approved_before

    def test_online_rate_without_flag_does_not_touch_schedules(
        self, management_client, teacher_user, school_settings, online_schedule
    ):
        before = online_schedule.teacher_rate

        response = management_client.patch(
            self._url(teacher_user),
            {"online_hourly_rate": str(_override(school_settings))},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["schedules_updated"] == 0
        online_schedule.refresh_from_db()
        assert online_schedule.teacher_rate == before

    def test_online_null_with_flag_reprices_to_school_rate(
        self, management_client, teacher_user, student, school, school_settings, db
    ):
        teacher_user.online_hourly_rate = _override(school_settings)
        teacher_user.save()
        sched = RecurringLessonsSchedule.objects.create(
            teacher=teacher_user, student=student, school=school,
            day_of_week=1, start_time="10:00", duration=Decimal("1.0"),
            lesson_type="online", start_date=date(2026, 1, 1),
        )
        assert sched.teacher_rate == teacher_user.online_hourly_rate

        response = management_client.patch(
            self._url(teacher_user),
            {"online_hourly_rate": None, "apply_to_schedules": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        sched.refresh_from_db()
        assert sched.teacher_rate == school_settings.online_teacher_rate


@pytest.mark.django_db
class TestBatchAddLessonOnlineRate:
    """batch_add_lesson resolves each teacher's own online rate (MAP-163)."""

    def _setup(self, teacher, school, email):
        pupil = User.objects.create_user(
            email=email, password="pass", user_type="student",
            first_name="Batch", last_name="Pupil", school=school, is_approved=True,
        )
        pupil.assigned_teachers.add(teacher)
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher, school=school, month=6, year=2026, status="draft",
        )
        client = APIClient()
        client.force_authenticate(user=teacher)
        return pupil, batch, client

    def _add(self, client, batch, pupil):
        return client.post(
            reverse("batch_add_lesson", kwargs={"batch_id": batch.pk}),
            {
                "student": pupil.pk, "scheduled_date": "2026-06-10",
                "start_time": "14:00:00", "duration": "1.0",
                "lesson_type": "online", "status": "completed",
            },
            format="json",
        )

    def test_batch_add_lesson_online_item_uses_teachers_rate(
        self, teacher_user, school, school_settings, db
    ):
        override_teacher = User.objects.create_user(
            email="override@ratetest.com", password="pass", user_type="teacher",
            first_name="Over", last_name="Ride", school=school, is_approved=True,
            hourly_rate=teacher_user.hourly_rate,
            online_hourly_rate=_override(school_settings),
        )
        pupil_a, batch_a, client_a = self._setup(override_teacher, school, "a@ratetest.com")
        pupil_b, batch_b, client_b = self._setup(teacher_user, school, "b@ratetest.com")

        resp_a = self._add(client_a, batch_a, pupil_a)
        resp_b = self._add(client_b, batch_b, pupil_b)

        assert resp_a.status_code == status.HTTP_201_CREATED
        assert resp_b.status_code == status.HTTP_201_CREATED
        item_a = BatchLessonItem.objects.get(pk=resp_a.data["id"])
        item_b = BatchLessonItem.objects.get(pk=resp_b.data["id"])
        assert item_a.teacher_rate == override_teacher.online_hourly_rate
        assert item_b.teacher_rate == school_settings.online_teacher_rate
