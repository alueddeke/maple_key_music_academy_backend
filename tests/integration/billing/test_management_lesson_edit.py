"""
Integration tests for management lesson item editing in batch invoice review.

Tests pin the contract for PATCH /management/batches/<batch_id>/lessons/<item_id>/:
  - All editable fields (scheduled_date, start_time, duration, lesson_type,
    status, teacher_notes, admin_notes) can be updated on submitted batches
  - Approved batches are immutable — editing is blocked with 400
  - admin_notes is optional — omitting it does not cause an error
  - Duration changes are reflected in teacher_payment in the response
  - Invalid field values (lesson_type, status) are rejected with 400
  - Non-management users receive 403
"""

import pytest
from decimal import Decimal
from datetime import date, time
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

from billing.models import (
    MonthlyInvoiceBatch,
    BatchLessonItem,
    Lesson,
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
def teacher_client(api_client, teacher_user):
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def student(school, db):
    return User.objects.create_user(
        email="student@edittest.com",
        password="pass",
        user_type="student",
        first_name="Edit",
        last_name="Student",
        school=school,
        is_approved=True,
    )


@pytest.fixture
def submitted_batch(teacher_user, student, school, school_settings, db):
    """Submitted batch with one lesson item at 1 hour (teacher rate $80 → $80 payment)."""
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
        scheduled_date=date(2026, 4, 15),
        start_time=time(15, 0),
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=Decimal("80.00"),
        student_rate=Decimal("100.00"),
        status="completed",
        teacher_notes="Original note",
    )
    return batch


@pytest.fixture
def approved_batch(teacher_user, student, school, school_settings, db):
    """Approved batch — must be immutable."""
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
        scheduled_date=date(2026, 3, 10),
        start_time=time(14, 0),
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=Decimal("80.00"),
        student_rate=Decimal("100.00"),
        status="completed",
    )
    return batch


def lesson_item(batch):
    return batch.lesson_items.first()


def edit_url(batch, item):
    return reverse(
        "management_edit_lesson_notes",
        kwargs={"batch_id": batch.pk, "item_id": item.pk},
    )


@pytest.mark.django_db
class TestManagementLessonEditFields:

    def test_can_edit_scheduled_date(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"scheduled_date": "2026-04-20"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.scheduled_date == date(2026, 4, 20)

    def test_can_edit_start_time(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"start_time": "10:00:00"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.start_time == time(10, 0)

    def test_can_edit_duration(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"duration": "0.5"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.duration == Decimal("0.5")

    def test_can_edit_lesson_type(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"lesson_type": "online"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.lesson_type == "online"

    def test_can_edit_status(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"status": "cancelled"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.status == "cancelled"

    def test_can_edit_status_trial(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"status": "trial"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.status == "trial"

    def test_can_edit_teacher_notes(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"teacher_notes": "Updated note"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.teacher_notes == "Updated note"

    def test_can_edit_admin_notes(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"admin_notes": "Duration corrected per teacher request"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.admin_notes == "Duration corrected per teacher request"

    def test_admin_notes_is_optional(self, management_client, submitted_batch):
        """PATCH without admin_notes must succeed — field is never required."""
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"teacher_notes": "Only updating notes"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

    def test_all_fields_at_once(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        payload = {
            "scheduled_date": "2026-04-22",
            "start_time": "11:00:00",
            "duration": "0.75",
            "lesson_type": "online",
            "status": "completed",
            "teacher_notes": "Multi-field update",
            "admin_notes": "Admin override",
        }
        response = management_client.patch(
            edit_url(submitted_batch, item), payload, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.scheduled_date == date(2026, 4, 22)
        assert item.lesson_type == "online"
        assert item.duration == Decimal("0.75")
        assert item.admin_notes == "Admin override"


@pytest.mark.django_db
class TestManagementLessonEditFinancial:

    def test_duration_change_updates_teacher_payment_in_response(
        self, management_client, submitted_batch
    ):
        """Response reflects recalculated teacher_payment after duration change."""
        item = lesson_item(submitted_batch)
        # Original: $80/hr × 1hr = $80. New: $80/hr × 0.5hr = $40
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"duration": "0.5"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert float(response.data["teacher_payment"]) == pytest.approx(40.0)

    def test_cancelled_status_zeros_teacher_payment(
        self, management_client, submitted_batch
    ):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"status": "cancelled"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert float(response.data["teacher_payment"]) == pytest.approx(0.0)


@pytest.mark.django_db
class TestManagementLessonEditRestrictions:

    def test_edit_blocked_on_approved_batch(self, management_client, approved_batch):
        item = lesson_item(approved_batch)
        response = management_client.patch(
            edit_url(approved_batch, item),
            {"teacher_notes": "Should not work"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_lesson_type_rejected(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"lesson_type": "invalid_type"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_status_rejected(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"status": "not_a_status"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_positive_duration_rejected(self, management_client, submitted_batch):
        item = lesson_item(submitted_batch)
        response = management_client.patch(
            edit_url(submitted_batch, item),
            {"duration": "0"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_teacher_cannot_use_management_edit_endpoint(
        self, teacher_client, submitted_batch
    ):
        item = lesson_item(submitted_batch)
        response = teacher_client.patch(
            edit_url(submitted_batch, item),
            {"teacher_notes": "Teacher trying management endpoint"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestAutoTrialStatus:
    """Verifies that first-time students (no prior Lesson records) get status='trial' automatically."""

    @pytest.fixture
    def draft_batch(self, teacher_user, school, db):
        return MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user,
            school=school,
            month=5,
            year=2026,
            status="draft",
        )

    @pytest.fixture
    def first_time_student(self, school, db):
        """Student with zero prior Lesson records — will trigger trial auto-detection."""
        return User.objects.create_user(
            email="firsttime@edittest.com",
            password="pass",
            user_type="student",
            first_name="First",
            last_name="Timer",
            school=school,
            is_approved=True,
        )

    @pytest.fixture
    def teacher_client(self, api_client, teacher_user):
        api_client.force_authenticate(user=teacher_user)
        return api_client

    def test_batch_add_lesson_sets_trial_for_first_time_student(
        self, teacher_client, draft_batch, first_time_student
    ):
        """batch_add_lesson auto-sets status='trial' when student has no prior Lesson records."""
        url = reverse("batch_add_lesson", kwargs={"batch_id": draft_batch.pk})
        response = teacher_client.post(
            url,
            {
                "student": first_time_student.pk,
                "scheduled_date": "2026-05-15",
                "start_time": "14:00:00",
                "duration": "1.0",
                "lesson_type": "in_person",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["status"] == "trial"


@pytest.mark.django_db
class TestManagementApproveTrialBatch:
    """Verifies that trial-only batches are approved correctly — no StudentInvoice created."""

    @pytest.fixture
    def trial_student(self, school, db):
        from billing.models import BillableContact
        student = User.objects.create_user(
            email="trialstudent@approvetest.com",
            password="pass",
            user_type="student",
            first_name="Trial",
            last_name="ApproveStudent",
            school=school,
            is_approved=True,
        )
        BillableContact.objects.create(
            school=school,
            student=student,
            is_primary=True,
            first_name="Trial",
            last_name="Parent",
            email="trialparent@approvetest.com",
            phone="555-1234",
            street_address="1 Trial St",
            city="Toronto",
            province="ON",
            postal_code="M1A 1A1",
        )
        return student

    @pytest.fixture
    def trial_batch(self, teacher_user, trial_student, school, school_settings, db):
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user,
            school=school,
            month=5,
            year=2026,
            status="submitted",
        )
        BatchLessonItem.objects.create(
            batch=batch,
            student=trial_student,
            scheduled_date=date(2026, 5, 10),
            start_time=time(15, 0),
            duration=Decimal("1.0"),
            lesson_type="in_person",
            teacher_rate=Decimal("80.00"),
            student_rate=Decimal("0.00"),
            status="trial",
        )
        return batch

    def test_approve_trial_batch_creates_lesson_not_invoice(
        self, management_client, trial_batch, trial_student
    ):
        from billing.models import Lesson, StudentInvoice
        url = reverse("management_approve_batch", kwargs={"batch_id": trial_batch.pk})
        response = management_client.post(url, format="json")
        assert response.status_code == status.HTTP_200_OK
        trial_lessons = Lesson.objects.filter(student=trial_student, is_trial=True)
        assert trial_lessons.count() == 1
        assert trial_lessons.first().student_rate == Decimal("0.00")
        assert StudentInvoice.objects.filter(batch=trial_batch).count() == 0
        trial_batch.refresh_from_db()
        assert trial_batch.status == "approved"
