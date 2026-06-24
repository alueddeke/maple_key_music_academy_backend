"""
Unit tests for Phase 21 dashboard summary card aggregation helper.

RED until Plan 02 Task 2 introduces compute_dashboard_summary in
billing/views/management.py.

Tests exercise compute_dashboard_summary(batch, school) directly (pure function).
Uses @pytest.mark.django_db for DB access but no APIClient overhead.

Coverage (Phase 16 Principles):
  - income_pre_expenses = sum of StudentInvoice.amount for the period
  - expenses_amount from SchoolExpenseItem sum (0.00 if no records)
  - income_after_expenses = income_pre_expenses - expenses_amount
  - total_teacher_pay = sum of Invoice.total_amount for teacher_payment invoices in period
  - income_after_payroll = income_after_expenses - total_teacher_pay
  - No floor: income_after_payroll can be negative
"""

import pytest
from decimal import Decimal
from datetime import date

from django.contrib.auth import get_user_model

from billing.models import (
    MonthlyInvoiceBatch,
    StudentInvoice,
    Invoice,
    SchoolExpenseItem,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Import the helper — RED state if compute_dashboard_summary does not exist yet.
# This import error is the expected RED indicator.
# ---------------------------------------------------------------------------
try:
    from billing.views.management import compute_dashboard_summary
    HELPER_AVAILABLE = True
except ImportError:
    HELPER_AVAILABLE = False
    compute_dashboard_summary = None


# ---------------------------------------------------------------------------
# Local factory helpers
# ---------------------------------------------------------------------------

def _make_batch(teacher, school, status='approved', month=6, year=2026):
    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher,
        school=school,
        month=month,
        year=year,
        status=status,
    )


def _make_teacher_invoice(school, teacher, total_amount=Decimal("150.00"), status='pending'):
    return Invoice.objects.create(
        school=school,
        teacher=teacher,
        invoice_type='teacher_payment',
        total_amount=total_amount,
        payment_balance=total_amount,
        status=status,
        created_by=teacher,
    )


def _make_student_invoice(batch, student, school, amount=Decimal("100.00")):
    invoice_number = f"INV-{batch.year}-{batch.month:02d}-S{student.pk}-{batch.pk}"
    return StudentInvoice.objects.create(
        batch=batch,
        student=student,
        school=school,
        invoice_number=invoice_number,
        amount=amount,
        credit_applied=Decimal("0.00"),
        amount_after_credit=amount,
        billing_contact_name=student.get_full_name(),
        billing_email=student.email,
        billing_phone="555-0100",
        billing_street_address="123 Test St",
        billing_city="Toronto",
        billing_province="ON",
        billing_postal_code="M5H 2N2",
    )


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_summary_aggregation_no_expenses(school, teacher_user, db):
    """
    3 StudentInvoice records (100+200+300=600), no SchoolMonthlyExpenses, teacher Invoice=150.

    Expected:
      income_pre_expenses  = '600.00'
      expenses_amount      = '0.00'
      income_after_expenses = '600.00'
      income_after_payroll = '450.00'

    RED until compute_dashboard_summary exists.
    """
    assert HELPER_AVAILABLE, (
        "compute_dashboard_summary not yet importable — RED state is expected. "
        "Task 2 must implement the helper in billing/views/management.py."
    )

    # Setup students
    student1 = User.objects.create_user(
        email="agg_student1@test.com", password="testpass123",
        user_type="student", first_name="S1", last_name="Test",
        school=school, is_approved=True,
    )
    student2 = User.objects.create_user(
        email="agg_student2@test.com", password="testpass123",
        user_type="student", first_name="S2", last_name="Test",
        school=school, is_approved=True,
    )
    student3 = User.objects.create_user(
        email="agg_student3@test.com", password="testpass123",
        user_type="student", first_name="S3", last_name="Test",
        school=school, is_approved=True,
    )

    teacher_invoice = _make_teacher_invoice(school, teacher_user, total_amount=Decimal("150.00"))
    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    batch.invoice = teacher_invoice
    batch.save()

    _make_student_invoice(batch, student1, school, amount=Decimal("100.00"))
    _make_student_invoice(batch, student2, school, amount=Decimal("200.00"))
    _make_student_invoice(batch, student3, school, amount=Decimal("300.00"))

    result = compute_dashboard_summary(batch, school)

    assert result['income_pre_expenses'] == '600.00', (
        f"Expected '600.00', got '{result['income_pre_expenses']}'"
    )
    assert result['expenses_amount'] == '0.00', (
        f"Expected '0.00' (no expenses record), got '{result['expenses_amount']}'"
    )
    assert result['income_after_expenses'] == '600.00', (
        f"Expected '600.00', got '{result['income_after_expenses']}'"
    )
    assert result['income_after_payroll'] == '450.00', (
        f"Expected '450.00' (600 - 150), got '{result['income_after_payroll']}'"
    )


@pytest.mark.django_db
def test_summary_aggregation_with_expenses(school, teacher_user, db):
    """
    Same setup + SchoolMonthlyExpenses.amount=100.

    Expected:
      income_pre_expenses  = '600.00'
      expenses_amount      = '100.00'
      income_after_expenses = '500.00'
      income_after_payroll = '350.00'
    """
    assert HELPER_AVAILABLE, (
        "compute_dashboard_summary not yet importable — RED state is expected."
    )

    student1 = User.objects.create_user(
        email="exp_student1@test.com", password="testpass123",
        user_type="student", first_name="E1", last_name="Test",
        school=school, is_approved=True,
    )
    student2 = User.objects.create_user(
        email="exp_student2@test.com", password="testpass123",
        user_type="student", first_name="E2", last_name="Test",
        school=school, is_approved=True,
    )
    student3 = User.objects.create_user(
        email="exp_student3@test.com", password="testpass123",
        user_type="student", first_name="E3", last_name="Test",
        school=school, is_approved=True,
    )

    teacher_invoice = _make_teacher_invoice(school, teacher_user, total_amount=Decimal("150.00"))
    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    batch.invoice = teacher_invoice
    batch.save()

    _make_student_invoice(batch, student1, school, amount=Decimal("100.00"))
    _make_student_invoice(batch, student2, school, amount=Decimal("200.00"))
    _make_student_invoice(batch, student3, school, amount=Decimal("300.00"))

    SchoolExpenseItem.objects.create(
        school=school,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        title='Test expense',
        amount=Decimal('100.00'),
        notes='test expenses',
    )

    result = compute_dashboard_summary(batch, school)

    assert result['income_pre_expenses'] == '600.00', (
        f"Expected '600.00', got '{result['income_pre_expenses']}'"
    )
    assert result['expenses_amount'] == '100.00', (
        f"Expected '100.00', got '{result['expenses_amount']}'"
    )
    assert result['income_after_expenses'] == '500.00', (
        f"Expected '500.00' (600 - 100), got '{result['income_after_expenses']}'"
    )
    assert result['income_after_payroll'] == '350.00', (
        f"Expected '350.00' (500 - 150), got '{result['income_after_payroll']}'"
    )


@pytest.mark.django_db
def test_summary_aggregation_zero_invoices(school, teacher_user, db):
    """
    Batch with no StudentInvoice rows → income_pre_expenses == Decimal type '0.00'.
    Verifies Decimal, not int 0 (no implicit type coercion).
    """
    assert HELPER_AVAILABLE, (
        "compute_dashboard_summary not yet importable — RED state is expected."
    )

    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)

    result = compute_dashboard_summary(batch, school)

    assert result['income_pre_expenses'] == '0.00', (
        f"Expected '0.00' (string Decimal), got '{result['income_pre_expenses']}'"
    )
    # Also verify it's a string representation of Decimal, not int
    assert isinstance(result['income_pre_expenses'], str), (
        f"Expected str, got {type(result['income_pre_expenses'])}"
    )


@pytest.mark.django_db
def test_summary_aggregation_negative_after_payroll(school, teacher_user, db):
    """
    income=100, expenses=50, teacher_payroll=200 → income_after_payroll = -150.00 (no floor).
    """
    assert HELPER_AVAILABLE, (
        "compute_dashboard_summary not yet importable — RED state is expected."
    )

    student1 = User.objects.create_user(
        email="neg_student1@test.com", password="testpass123",
        user_type="student", first_name="N1", last_name="Test",
        school=school, is_approved=True,
    )

    teacher_invoice = _make_teacher_invoice(school, teacher_user, total_amount=Decimal("200.00"))
    batch = _make_batch(teacher_user, school, status='approved', month=6, year=2026)
    batch.invoice = teacher_invoice
    batch.save()

    _make_student_invoice(batch, student1, school, amount=Decimal("100.00"))

    SchoolExpenseItem.objects.create(
        school=school,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        title='Test expense',
        amount=Decimal('50.00'),
        notes='heavy month',
    )

    result = compute_dashboard_summary(batch, school)

    assert result['income_pre_expenses'] == '100.00', (
        f"Expected '100.00', got '{result['income_pre_expenses']}'"
    )
    assert result['income_after_expenses'] == '50.00', (
        f"Expected '50.00' (100 - 50), got '{result['income_after_expenses']}'"
    )
    assert result['income_after_payroll'] == '-150.00', (
        f"Expected '-150.00' (50 - 200, no floor), got '{result['income_after_payroll']}'"
    )
