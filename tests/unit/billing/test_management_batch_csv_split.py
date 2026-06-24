"""
Unit tests for HELM-05: management_approve_batch returns JSON (not CSV),
and new management_batch_csv GET endpoint serves CSV for approved batches.

Tests prove:
- D-18: POST /approve/ returns {status, batch_id, invoice_count} JSON
- D-19: GET /csv/ serves the Helcim CSV for already-approved batches
- D-21: GET /csv/ returns 400 when batch is not yet approved
- T-18-D1: GET /csv/ returns 404 for wrong school (school isolation)
- T-18-D5: GET /csv/ returns 403 for non-management users
- T-18-D6: GET /csv/ returns 401 for unauthenticated requests
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
    StudentInvoice,
    BillableContact,
    SchoolSettings,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def management_client(management_user):
    """Authenticated APIClient for the primary school's management user."""
    client = APIClient()
    client.force_authenticate(user=management_user)
    return client


@pytest.fixture
def teacher_client(teacher_user):
    """Authenticated APIClient for the primary school's teacher user."""
    client = APIClient()
    client.force_authenticate(user=teacher_user)
    return client


@pytest.fixture
def student_with_contact(school, db):
    """Student with complete billable contact so batch approval succeeds."""
    student = User.objects.create_user(
        email="csv_split_student@test.com",
        password="pass",
        user_type="student",
        first_name="CSV",
        last_name="Student",
        school=school,
        is_approved=True,
    )
    BillableContact.objects.create(
        student=student,
        school=school,
        contact_type="parent",
        first_name="CSV",
        last_name="Parent",
        email="csvparent@test.com",
        phone="416-555-0099",
        street_address="99 CSV St",
        city="Toronto",
        province="ON",
        postal_code="M9A 1A1",
        is_primary=True,
    )
    return student


@pytest.fixture
def submitted_batch(school, teacher_user, student_with_contact, school_settings, db):
    """
    A submitted MonthlyInvoiceBatch with one completed lesson item.

    student_with_contact has a prior lesson record created via student_user fixture
    pattern, so items added with status='completed' won't be auto-promoted to 'trial'.
    We create the batch manually and add one completed item directly to guarantee a
    predictable invoice_count of 1 on approval.
    """
    from billing.models import Lesson
    from django.utils import timezone

    # Give the student one prior lesson so auto-trial detection won't fire
    Lesson.objects.create(
        teacher=teacher_user,
        student=student_with_contact,
        school=school,
        lesson_type="online",
        is_trial=True,
        teacher_rate=Decimal("45.00"),
        student_rate=Decimal("0.00"),
        scheduled_date=timezone.now() - timezone.timedelta(days=60),
        duration=1.0,
        status="completed",
    )

    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=school,
        month=4,
        year=2026,
        status="submitted",
    )
    # BatchLessonItem does not have a 'school' FK — school is inherited from batch.school
    BatchLessonItem.objects.create(
        batch=batch,
        student=student_with_contact,
        scheduled_date=date(2026, 4, 10),
        start_time=time(15, 0),
        duration=Decimal("1.0"),
        lesson_type="online",
        status="completed",
        teacher_rate=Decimal("45.00"),
        student_rate=Decimal("60.00"),
    )
    return batch


@pytest.fixture
def approved_batch(management_client, submitted_batch):
    """
    Approve the submitted_batch via the POST endpoint and return the
    MonthlyInvoiceBatch ORM object refreshed from DB.
    """
    url = reverse("management_approve_batch", kwargs={"batch_id": submitted_batch.id})
    response = management_client.post(url, format="json")
    assert response.status_code == status.HTTP_200_OK, (
        f"Fixture approval failed: {response.content}"
    )
    submitted_batch.refresh_from_db()
    return submitted_batch


@pytest.fixture
def second_school_management_user(second_school, db):
    """Management user belonging to second_school."""
    return User.objects.create_user(
        email="mgmt@secondschool.com",
        password="pass",
        user_type="management",
        first_name="Second",
        last_name="Manager",
        school=second_school,
        is_approved=True,
    )


@pytest.fixture
def second_school_client(second_school_management_user):
    """Authenticated client for second_school management user."""
    client = APIClient()
    client.force_authenticate(user=second_school_management_user)
    return client


# ---------------------------------------------------------------------------
# Tests — POST /approve/ returns JSON (D-18)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_approve_returns_json_not_csv(management_client, submitted_batch):
    """
    POST /approve/ must return JSON {status, batch_id, invoice_count}, NOT a CSV blob.
    Proves D-18.
    """
    url = reverse("management_approve_batch", kwargs={"batch_id": submitted_batch.id})
    response = management_client.post(url, format="json")

    assert response.status_code == status.HTTP_200_OK
    # Content-Type must be JSON, not CSV
    assert response["Content-Type"].startswith("application/json"), (
        f"Expected JSON Content-Type, got: {response['Content-Type']}"
    )
    data = response.json()
    assert data["status"] == "approved"
    assert data["batch_id"] == submitted_batch.id
    assert data["invoice_count"] == 1


@pytest.mark.django_db
def test_approve_no_longer_emits_csv_body(management_client, submitted_batch):
    """
    POST /approve/ must NOT return a CSV body.
    The CSV is served by the separate GET /csv/ endpoint (HELM-05).
    """
    url = reverse("management_approve_batch", kwargs={"batch_id": submitted_batch.id})
    response = management_client.post(url, format="json")

    assert response.status_code == status.HTTP_200_OK
    content_type = response.get("Content-Type", "")
    assert "text/csv" not in content_type, (
        f"approve POST must not return CSV; Content-Type was: {content_type}"
    )


@pytest.mark.django_db
def test_approve_still_creates_student_invoices(management_client, submitted_batch):
    """
    The JSON refactor must not break Lesson + StudentInvoice creation.
    After approval, exactly 1 StudentInvoice row exists for the batch.
    Proves the transaction.atomic() block is intact.
    """
    assert StudentInvoice.objects.filter(batch=submitted_batch).count() == 0

    url = reverse("management_approve_batch", kwargs={"batch_id": submitted_batch.id})
    response = management_client.post(url, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert StudentInvoice.objects.filter(batch=submitted_batch).count() == 1


# ---------------------------------------------------------------------------
# Tests — GET /csv/ endpoint (D-19, D-21, T-18-D1, T-18-D5, T-18-D6)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_csv_endpoint_returns_csv_for_approved_batch(management_client, approved_batch):
    """
    GET /csv/ on an approved batch returns 200 with text/csv Content-Type and a
    non-empty body (HELM-05 D-19 happy path).
    """
    url = reverse("management_batch_csv", kwargs={"batch_id": approved_batch.id})
    response = management_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert "text/csv" in response.get("Content-Type", ""), (
        f"Expected text/csv, got: {response.get('Content-Type', '')}"
    )
    assert len(response.content) > 0, "CSV response body must not be empty"


@pytest.mark.django_db
def test_csv_endpoint_returns_400_when_not_approved(management_client, submitted_batch):
    """
    GET /csv/ on a batch that is 'submitted' (not 'approved') returns 400 (D-21).
    Premature download is blocked.
    """
    assert submitted_batch.status == "submitted"
    url = reverse("management_batch_csv", kwargs={"batch_id": submitted_batch.id})
    response = management_client.get(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_csv_endpoint_returns_404_for_other_school(second_school_client, approved_batch):
    """
    GET /csv/ by a management user from a different school returns 404.
    Cross-school access is blocked — 404 (not 403) per school isolation convention
    (ARCHITECTURE.md: do not reveal existence of resources to wrong-school users).
    Proves T-18-D1.
    """
    url = reverse("management_batch_csv", kwargs={"batch_id": approved_batch.id})
    response = second_school_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_csv_endpoint_requires_management_role(teacher_client, approved_batch):
    """
    GET /csv/ as a teacher (non-management user) returns 403.
    Proves T-18-D5.
    """
    url = reverse("management_batch_csv", kwargs={"batch_id": approved_batch.id})
    response = teacher_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_csv_endpoint_unauthenticated_returns_401(db, approved_batch):
    """
    GET /csv/ without authentication returns 401.
    Proves T-18-D6.
    """
    client = APIClient()  # No auth
    url = reverse("management_batch_csv", kwargs={"batch_id": approved_batch.id})
    response = client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
