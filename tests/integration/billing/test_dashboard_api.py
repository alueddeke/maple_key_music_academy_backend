"""
Wave 0 RED stubs — turn GREEN when Plan 02 Task 2 lands the 4 dashboard view functions.

Integration tests for Phase 21 Dashboard API endpoints:
  - GET  /api/billing/management/dashboard/batches/      (DASH-01/02/03/04)
  - GET  /api/billing/management/dashboard/{batch_id}/   (DASH-01/02/03/04)
  - PATCH /api/billing/management/invoices/{pk}/         (DASH-03)
  - PUT  /api/billing/management/expenses/{batch_id}/    (DASH-04)

Covers happy paths, school isolation, auth enforcement, and edge cases.
All assertions explicit (Phase 16 Principle 6: no implicit defaults).
"""

import pytest
from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from billing.models import (
    MonthlyInvoiceBatch,
    StudentInvoice,
    Invoice,
    SchoolMonthlyExpenses,
    PreBillingInvoice,
    School,
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
def second_school_management_user(second_school, db):
    """Management user belonging to school B."""
    return User.objects.create_user(
        email="mgmt_school_b@test.com",
        password="testpass123",
        user_type="management",
        first_name="School",
        last_name="B Manager",
        school=second_school,
        is_approved=True,
    )


@pytest.fixture
def second_school_management_client(second_school_management_user):
    """Authenticated APIClient for school B management user."""
    client = APIClient()
    client.force_authenticate(user=second_school_management_user)
    return client


@pytest.fixture
def teacher_b(second_school, db):
    """Teacher in school B."""
    return User.objects.create_user(
        email="teacher_b@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Teacher",
        last_name="B",
        hourly_rate=Decimal("80.00"),
        school=second_school,
        is_approved=True,
    )


@pytest.fixture
def student_a(school, db):
    """Student in school A."""
    return User.objects.create_user(
        email="student_a@test.com",
        password="testpass123",
        user_type="student",
        first_name="Alice",
        last_name="Student",
        school=school,
        is_approved=True,
    )


@pytest.fixture
def student_a2(school, db):
    """Second student in school A."""
    return User.objects.create_user(
        email="student_a2@test.com",
        password="testpass123",
        user_type="student",
        first_name="Bob",
        last_name="Student",
        school=school,
        is_approved=True,
    )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_batch(teacher, school, status='approved', month=6, year=2026):
    """Create a MonthlyInvoiceBatch with the given status."""
    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher,
        school=school,
        month=month,
        year=year,
        status=status,
    )


def _make_teacher_invoice(school, teacher, total_amount=Decimal("150.00"), status='pending'):
    """Create a teacher_payment Invoice."""
    return Invoice.objects.create(
        school=school,
        teacher=teacher,
        invoice_type='teacher_payment',
        total_amount=total_amount,
        payment_balance=total_amount,
        status=status,
        created_by=teacher,
    )


def _make_student_invoice(
    batch,
    student,
    school,
    amount=Decimal("120.00"),
    credit_applied=Decimal("0.00"),
    amount_after_credit=Decimal("120.00"),
):
    """Create a StudentInvoice for a given batch and student."""
    # invoice_number must be unique
    invoice_number = f"INV-{batch.year}-{batch.month:02d}-S{student.pk}-{batch.pk}"
    return StudentInvoice.objects.create(
        batch=batch,
        student=student,
        school=school,
        invoice_number=invoice_number,
        amount=amount,
        credit_applied=credit_applied,
        amount_after_credit=amount_after_credit,
        billing_contact_name=student.get_full_name(),
        billing_email=student.email,
        billing_phone="555-0100",
        billing_street_address="123 Test St",
        billing_city="Toronto",
        billing_province="ON",
        billing_postal_code="M5H 2N2",
    )


# ---------------------------------------------------------------------------
# DASH-01/02/03/04 — GET /management/dashboard/batches/
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_dashboard_batches_returns_approved_only(management_client, school, teacher_user):
    """
    Endpoint returns only approved batches, not pending/submitted ones.

    Happy path: approved batch visible.
    Failing path: submitted batch not in response.
    """
    approved = _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    _make_batch(teacher_user, school, status='submitted', month=5, year=2026)

    response = management_client.get('/api/billing/management/dashboard/batches/')

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    batch_ids = [item['batch_id'] for item in response.json()]
    assert approved.id in batch_ids, f"Approved batch {approved.id} not in response: {batch_ids}"
    assert len(batch_ids) == 1, f"Expected 1 result (only approved), got {len(batch_ids)}: {batch_ids}"


@pytest.mark.django_db
def test_dashboard_batches_newest_first(management_client, school, teacher_user):
    """
    Batches list is ordered newest (highest year/month) first.
    """
    older = _make_batch(teacher_user, school, status='approved', month=4, year=2026)
    newer = _make_batch(teacher_user, school, status='approved', month=6, year=2026)

    response = management_client.get('/api/billing/management/dashboard/batches/')

    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    items = response.json()
    assert len(items) == 2, f"Expected 2 items, got {len(items)}"
    assert items[0]['batch_id'] == newer.id, (
        f"Expected newest batch {newer.id} first, got {items[0]['batch_id']}"
    )
    assert items[1]['batch_id'] == older.id, (
        f"Expected older batch {older.id} second, got {items[1]['batch_id']}"
    )


@pytest.mark.django_db
def test_dashboard_batches_deduplicates_period(management_client, school, teacher_user, db):
    """
    Two approved batches for same (year, month) different teachers → single entry in response.
    The period selector should show one entry per period, not one per teacher.
    """
    teacher2 = User.objects.create_user(
        email="teacher2@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Second",
        last_name="Teacher",
        hourly_rate=Decimal("70.00"),
        school=school,
        is_approved=True,
    )

    _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    _make_batch(teacher2, school, status='approved', month=6, year=2026)

    response = management_client.get('/api/billing/management/dashboard/batches/')

    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    items = response.json()
    assert len(items) == 1, (
        f"Expected 1 deduplicated entry for June 2026, got {len(items)}: {items}"
    )
    assert items[0]['period_start'] == '2026-06-01', (
        f"Expected period_start '2026-06-01', got {items[0]['period_start']}"
    )
    assert items[0]['period_end'] == '2026-06-30', (
        f"Expected period_end '2026-06-30', got {items[0]['period_end']}"
    )
    assert items[0]['label'] == 'June 2026', (
        f"Expected label 'June 2026', got {items[0]['label']}"
    )


@pytest.mark.django_db
def test_dashboard_batches_school_isolation(
    management_client, school, teacher_user, second_school, teacher_b
):
    """
    School A management user sees only their school's approved batches.
    School B's batch must not appear in school A's response.
    """
    _make_batch(teacher_b, second_school, status='approved', month=6, year=2026)
    approved_a = _make_batch(teacher_user, school, status='approved', month=5, year=2026)

    response = management_client.get('/api/billing/management/dashboard/batches/')

    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    items = response.json()
    batch_ids = [item['batch_id'] for item in items]
    assert approved_a.id in batch_ids, f"School A batch not found in response"
    # School B's batch must NOT appear
    for item in items:
        assert item['batch_id'] != teacher_b.pk, (
            "School B batch leaked into school A response"
        )


# ---------------------------------------------------------------------------
# DASH-01/02/03/04 — GET /management/dashboard/{batch_id}/
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_student_billing_data(management_client, school, teacher_user, student_a, student_a2):
    """
    Dashboard data endpoint returns student_billing rows for all StudentInvoice records
    in the batch period, with required fields.
    """
    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    si1 = _make_student_invoice(
        batch, student_a, school,
        amount=Decimal("100.00"),
        credit_applied=Decimal("10.00"),
        amount_after_credit=Decimal("90.00"),
    )
    si2 = _make_student_invoice(
        batch, student_a2, school,
        amount=Decimal("200.00"),
        credit_applied=Decimal("0.00"),
        amount_after_credit=Decimal("200.00"),
    )

    response = management_client.get(f'/api/billing/management/dashboard/{batch.id}/')

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    data = response.json()
    assert 'student_billing' in data, f"'student_billing' key missing from response: {list(data.keys())}"
    assert len(data['student_billing']) == 2, (
        f"Expected 2 student_billing rows, got {len(data['student_billing'])}"
    )

    invoice_ids = {row['invoice_id'] for row in data['student_billing']}
    assert si1.id in invoice_ids, f"StudentInvoice {si1.id} not in student_billing rows"
    assert si2.id in invoice_ids, f"StudentInvoice {si2.id} not in student_billing rows"

    # Check required fields on first row
    for row in data['student_billing']:
        required_fields = ['invoice_id', 'student_name', 'amount', 'credit_applied',
                           'amount_after_credit', 'pre_billing_status']
        for field in required_fields:
            assert field in row, f"Field '{field}' missing from student_billing row: {row}"


@pytest.mark.django_db
def test_teacher_payroll_data(management_client, school, teacher_user):
    """
    Dashboard data endpoint returns teacher_payroll rows for approved batches with invoices.
    """
    teacher_invoice = _make_teacher_invoice(school, teacher_user, total_amount=Decimal("300.00"))
    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    batch.invoice = teacher_invoice
    batch.save()

    response = management_client.get(f'/api/billing/management/dashboard/{batch.id}/')

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    data = response.json()
    assert 'teacher_payroll' in data, f"'teacher_payroll' key missing: {list(data.keys())}"
    assert len(data['teacher_payroll']) == 1, (
        f"Expected 1 teacher_payroll row, got {len(data['teacher_payroll'])}"
    )

    row = data['teacher_payroll'][0]
    required_fields = ['invoice_id', 'teacher_name', 'teacher_email', 'gross', 'teacher_pay',
                       'paid_status', 'date_paid', 'reference_number']
    for field in required_fields:
        assert field in row, f"Field '{field}' missing from teacher_payroll row: {row}"

    assert row['invoice_id'] == teacher_invoice.id, (
        f"Expected invoice_id {teacher_invoice.id}, got {row['invoice_id']}"
    )
    assert row['teacher_email'] == teacher_user.email, (
        f"Expected teacher_email '{teacher_user.email}', got '{row['teacher_email']}'"
    )
    assert row['gross'] == '300.00', f"Expected gross '300.00', got '{row['gross']}'"
    assert row['date_paid'] is None, f"Expected date_paid None, got {row['date_paid']}"
    assert row['reference_number'] is None, (
        f"Expected reference_number None, got {row['reference_number']}"
    )


@pytest.mark.django_db
def test_teacher_payroll_aggregates_multiple_teachers(
    management_client, school, teacher_user, db
):
    """
    Two approved batches for same (year, month) but different teachers → both appear in
    teacher_payroll when querying either batch_id.
    """
    teacher2 = User.objects.create_user(
        email="teacher2_multi@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Multi",
        last_name="Teacher",
        hourly_rate=Decimal("70.00"),
        school=school,
        is_approved=True,
    )

    inv1 = _make_teacher_invoice(school, teacher_user, total_amount=Decimal("200.00"))
    inv2 = _make_teacher_invoice(school, teacher2, total_amount=Decimal("150.00"))

    batch1 = _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    batch1.invoice = inv1
    batch1.save()

    batch2 = _make_batch(teacher2, school, status='approved', month=6, year=2026)
    batch2.invoice = inv2
    batch2.save()

    # Query via batch1 — should still aggregate both teachers for June 2026
    response = management_client.get(f'/api/billing/management/dashboard/{batch1.id}/')

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    data = response.json()
    assert len(data['teacher_payroll']) == 2, (
        f"Expected 2 teacher_payroll rows (both teachers), got {len(data['teacher_payroll'])}"
    )


@pytest.mark.django_db
def test_dashboard_data_not_found(management_client):
    """GET /dashboard/99999/ returns 404 — batch does not exist."""
    response = management_client.get('/api/billing/management/dashboard/99999/')
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"


@pytest.mark.django_db
def test_dashboard_school_isolation(
    management_client, second_school, teacher_b
):
    """
    School A's management user gets 404 when accessing a batch belonging to school B.
    (not 403 — avoid existence disclosure)
    """
    batch_b = _make_batch(teacher_b, second_school, status='approved', month=6, year=2026)

    response = management_client.get(f'/api/billing/management/dashboard/{batch_b.id}/')
    assert response.status_code == 404, (
        f"Expected 404 for cross-school batch access, got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# DASH-03 — PATCH /management/invoices/{pk}/
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_patch_invoice_payroll_fields(management_client, school, teacher_user):
    """
    PATCH with date_paid + reference_number updates both fields.
    refresh_from_db verifies DB persistence (not just response).
    """
    invoice = _make_teacher_invoice(school, teacher_user)

    response = management_client.patch(
        f'/api/billing/management/invoices/{invoice.id}/',
        data={'date_paid': '2026-06-15', 'reference_number': 'REF-001'},
        format='json',
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    invoice.refresh_from_db()
    assert invoice.date_paid == date(2026, 6, 15), (
        f"Expected date(2026,6,15), got {invoice.date_paid}"
    )
    assert invoice.reference_number == 'REF-001', (
        f"Expected 'REF-001', got '{invoice.reference_number}'"
    )


@pytest.mark.django_db
def test_patch_invoice_empty_date(management_client, school, teacher_user):
    """
    PATCH with date_paid='' (empty string) sets date_paid to None (not ValidationError).
    Pitfall #5: empty string → None coercion for DateField.
    """
    invoice = _make_teacher_invoice(school, teacher_user)
    # Pre-set a date_paid
    invoice.date_paid = date(2026, 6, 1)
    invoice.save()

    response = management_client.patch(
        f'/api/billing/management/invoices/{invoice.id}/',
        data={'date_paid': ''},
        format='json',
    )

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.data}"
    )
    invoice.refresh_from_db()
    assert invoice.date_paid is None, (
        f"Expected date_paid to be None after empty-string PATCH, got {invoice.date_paid}"
    )


@pytest.mark.django_db
def test_patch_invoice_status_change(management_client, school, teacher_user):
    """
    PATCH with status='paid' updates the invoice status.
    """
    invoice = _make_teacher_invoice(school, teacher_user, status='pending')

    response = management_client.patch(
        f'/api/billing/management/invoices/{invoice.id}/',
        data={'status': 'paid'},
        format='json',
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    invoice.refresh_from_db()
    assert invoice.status == 'paid', f"Expected status 'paid', got '{invoice.status}'"


@pytest.mark.django_db
def test_patch_invoice_rejects_non_allowed_fields(management_client, school, teacher_user):
    """
    PATCH with total_amount (non-allowlisted field) is silently ignored.
    Allowlisted field (date_paid) is applied normally.

    T-21-07: PATCH allowlist enforcement — non-allowlisted fields silently ignored.
    """
    invoice = _make_teacher_invoice(school, teacher_user, total_amount=Decimal("200.00"))
    original_amount = invoice.total_amount

    response = management_client.patch(
        f'/api/billing/management/invoices/{invoice.id}/',
        data={'total_amount': '999.00', 'date_paid': '2026-06-15'},
        format='json',
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    invoice.refresh_from_db()
    assert invoice.total_amount == original_amount, (
        f"total_amount should be unchanged {original_amount}, got {invoice.total_amount}"
    )
    assert invoice.date_paid == date(2026, 6, 15), (
        f"Expected date_paid='2026-06-15', got {invoice.date_paid}"
    )


@pytest.mark.django_db
def test_patch_invoice_not_found(management_client):
    """PATCH /invoices/99999/ returns 404."""
    response = management_client.patch(
        '/api/billing/management/invoices/99999/',
        data={'status': 'paid'},
        format='json',
    )
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"


@pytest.mark.django_db
def test_patch_invoice_school_isolation(
    management_client, second_school, teacher_b
):
    """
    PATCH another school's invoice returns 404 (not 403 — avoid disclosing existence).
    T-21-10: existence-disclosure via 403 vs 404.
    """
    other_invoice = Invoice.objects.create(
        school=second_school,
        teacher=teacher_b,
        invoice_type='teacher_payment',
        total_amount=Decimal("200.00"),
        payment_balance=Decimal("200.00"),
        status='pending',
        created_by=teacher_b,
    )

    response = management_client.patch(
        f'/api/billing/management/invoices/{other_invoice.id}/',
        data={'status': 'paid'},
        format='json',
    )
    assert response.status_code == 404, (
        f"Expected 404 for cross-school PATCH, got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# DASH-04 — PUT /management/expenses/{batch_id}/
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_upsert_expenses_creates(management_client, school, teacher_user):
    """
    PUT /expenses/{batch_id}/ creates a new SchoolMonthlyExpenses record.
    Asserts: 200 response + DB record exists with correct values.
    """
    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)

    response = management_client.put(
        f'/api/billing/management/expenses/{batch.id}/',
        data={'amount': '500.00', 'notes': 'rent'},
        format='json',
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    assert SchoolMonthlyExpenses.objects.filter(
        school=school,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    ).exists(), "SchoolMonthlyExpenses record not created"

    record = SchoolMonthlyExpenses.objects.get(
        school=school,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    assert record.amount == Decimal('500.00'), (
        f"Expected amount 500.00, got {record.amount}"
    )
    assert record.notes == 'rent', f"Expected notes='rent', got '{record.notes}'"


@pytest.mark.django_db
def test_upsert_expenses_updates(management_client, school, teacher_user):
    """
    PUT /expenses/{batch_id}/ with an existing record updates rather than creating a duplicate.
    """
    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    # Pre-create an existing record
    SchoolMonthlyExpenses.objects.create(
        school=school,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        amount=Decimal('300.00'),
        notes='old notes',
    )

    response = management_client.put(
        f'/api/billing/management/expenses/{batch.id}/',
        data={'amount': '750.00', 'notes': 'updated notes'},
        format='json',
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    # Exactly 1 record (not 2)
    count = SchoolMonthlyExpenses.objects.filter(
        school=school,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    ).count()
    assert count == 1, f"Expected 1 record after update (no duplicate), got {count}"

    record = SchoolMonthlyExpenses.objects.get(
        school=school,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    assert record.amount == Decimal('750.00'), (
        f"Expected updated amount 750.00, got {record.amount}"
    )


@pytest.mark.django_db
def test_upsert_expenses_negative_amount_rejected(management_client, school, teacher_user):
    """
    PUT /expenses/{batch_id}/ with negative amount returns 400.
    T-21-09: negative amount validation.
    """
    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)

    response = management_client.put(
        f'/api/billing/management/expenses/{batch.id}/',
        data={'amount': '-1.00'},
        format='json',
    )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    assert 'error' in response.json(), f"Expected 'error' key in response: {response.json()}"
    assert response.json()['error'] == 'Amount must be >= 0', (
        f"Expected specific error message, got '{response.json()['error']}'"
    )
    # No record created
    assert not SchoolMonthlyExpenses.objects.filter(school=school).exists(), (
        "SchoolMonthlyExpenses record should NOT be created on negative amount"
    )


@pytest.mark.django_db
def test_upsert_expenses_school_isolation(
    management_client, second_school, teacher_b
):
    """
    PUT to another school's batch_id returns 404.
    """
    batch_b = _make_batch(teacher_b, second_school, status='approved', month=6, year=2026)

    response = management_client.put(
        f'/api/billing/management/expenses/{batch_b.id}/',
        data={'amount': '100.00'},
        format='json',
    )
    assert response.status_code == 404, (
        f"Expected 404 for cross-school expenses PUT, got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Summary card — cross-school expenses isolation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_dashboard_data_summary_excludes_other_school_expenses(
    management_client, school, teacher_user, second_school, teacher_b
):
    """
    School B's SchoolMonthlyExpenses must not affect school A's summary.
    School A should see expenses_amount='0.00' (default) when only school B has an expense record.
    """
    batch_a = _make_batch(teacher_user, school, status='approved', month=6, year=2026)

    # Create expenses for school B only
    SchoolMonthlyExpenses.objects.create(
        school=second_school,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        amount=Decimal('999.00'),
        notes='school B expenses',
    )

    response = management_client.get(f'/api/billing/management/dashboard/{batch_a.id}/')

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"
    data = response.json()
    assert 'summary' in data, f"'summary' key missing: {list(data.keys())}"
    assert data['summary']['expenses_amount'] == '0.00', (
        f"Expected expenses_amount '0.00' (school A has no expenses), "
        f"got '{data['summary']['expenses_amount']}' — school B data leaked!"
    )


# ---------------------------------------------------------------------------
# Auth enforcement — all 4 endpoints require management role
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_all_endpoints_require_management(school, teacher_user):
    """
    Anonymous client (no auth) receives 401 or 403 from each of the 4 dashboard URLs.
    All 4 endpoints enforced by @management_required (T-21-06).
    """
    anonymous = APIClient()
    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    invoice = _make_teacher_invoice(school, teacher_user)

    endpoints = [
        ('get', '/api/billing/management/dashboard/batches/'),
        ('get', f'/api/billing/management/dashboard/{batch.id}/'),
        ('patch', f'/api/billing/management/invoices/{invoice.id}/'),
        ('put', f'/api/billing/management/expenses/{batch.id}/'),
    ]

    for method, url in endpoints:
        response = getattr(anonymous, method)(url, format='json')
        assert response.status_code in (401, 403), (
            f"Expected 401 or 403 from anonymous {method.upper()} {url}, "
            f"got {response.status_code}"
        )
