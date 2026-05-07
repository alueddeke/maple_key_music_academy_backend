"""
Integration tests for invoice number generation race condition.

Tests verify that concurrent calls to generate_invoice_number() on both
Invoice and StudentInvoice models produce distinct, unique numbers.

Uses transaction=True on pytest.mark.django_db so each thread can commit
independently — required for select_for_update to actually serialize on
PostgreSQL. Without transaction=True the test runs in a single transaction
and select_for_update is a no-op.
"""

import inspect
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from billing.models import Invoice, MonthlyInvoiceBatch, StudentInvoice

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_school():
    """Create a fresh school (called inside threads that need a real DB conn)."""
    from billing.models import School
    return School.objects.create(
        name="Race Test School",
        subdomain="racetestschool",
        email="race@testschool.com",
        hst_rate=Decimal("13.00"),
        gst_rate=Decimal("5.00"),
        pst_rate=Decimal("0.00"),
        billing_cycle_day=1,
        payment_terms_days=7,
        cancellation_notice_hours=24,
        street_address="1 Race St",
        city="Toronto",
        province="ON",
        postal_code="M5H 2N2",
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Test 1 — Invoice concurrent number generation
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_invoice_number_generation_produces_unique_numbers(school, management_user):
    """Two concurrent calls to Invoice.generate_invoice_number() must not return the same number.

    Pre-seeds at least one Invoice row matching the current month prefix so the
    queryset is non-empty and select_for_update() has rows to lock.
    """
    today = datetime.now()
    prefix = f"INV-{today.strftime('%Y')}-{today.strftime('%m')}"

    # Pre-seed one Invoice row with the matching prefix so the lock has rows to acquire.
    Invoice.objects.create(
        school=school,
        invoice_type="teacher_payment",
        invoice_number=f"{prefix}-0001",
        payment_balance=Decimal("0.00"),
        total_amount=Decimal("0.00"),
        created_by=management_user,
    )

    def _generate():
        """Run inside a thread — close and re-open DB connection per thread."""
        connection.close()  # force a fresh DB connection per thread
        inv = Invoice()  # transient instance — generate_invoice_number does not save
        return inv.generate_invoice_number()

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_generate), ex.submit(_generate)]
        results = [f.result(timeout=10) for f in futures]

    assert results[0] != results[1], (
        f"Race condition: both threads returned the same invoice number {results[0]}"
    )


# ---------------------------------------------------------------------------
# Test 2 — StudentInvoice concurrent number generation
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_student_invoice_number_generation_produces_unique_numbers(
    school, teacher_user, management_user
):
    """Two concurrent calls to StudentInvoice.generate_invoice_number() for the same
    batch + student must produce distinct invoice_number values.

    Pre-seeds one StudentInvoice row so the lock has rows to acquire.
    """
    today = datetime.now()

    # Create a student user
    student = User.objects.create_user(
        email="race_student@test.com",
        password="testpass123",
        user_type="student",
        first_name="Race",
        last_name="Student",
        school=school,
        is_approved=True,
    )

    # Create a batch for the current month
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=school,
        month=today.month,
        year=today.year,
    )

    expected_prefix = f"INV-{batch.year}-{batch.month:02d}-S{student.id}"

    # Pre-seed one StudentInvoice row with the matching prefix so the lock has rows.
    # We set invoice_number manually to avoid triggering generate_invoice_number() inside save().
    si_seed = StudentInvoice(
        batch=batch,
        student=student,
        school=school,
        invoice_number=f"{expected_prefix}-0001",
        amount=Decimal("0.00"),
        billing_contact_name="Race Student",
        billing_email="race@test.com",
        billing_phone="4165551234",
        billing_street_address="1 Race St",
        billing_city="Toronto",
        billing_province="ON",
        billing_postal_code="M5H 2N2",
    )
    # Use update_or_create's underlying save bypass to avoid unique_together conflict.
    # We directly call super().save() pattern via update_fields trick.
    StudentInvoice.objects.bulk_create([si_seed])

    batch_id = batch.id
    student_id = student.id

    def _generate():
        """Run inside a thread — close and re-open DB connection per thread."""
        connection.close()  # force a fresh DB connection per thread
        # Re-fetch batch and student to avoid cross-thread ORM state sharing.
        _batch = MonthlyInvoiceBatch.objects.get(id=batch_id)
        _student = User.objects.get(id=student_id)
        inv = StudentInvoice(batch=_batch, student=_student)
        inv.generate_invoice_number()
        return inv.invoice_number

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_generate), ex.submit(_generate)]
        results = [f.result(timeout=10) for f in futures]

    assert results[0] != results[1], (
        f"Race condition: both threads returned the same student invoice number {results[0]}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Static source inspection canary
# ---------------------------------------------------------------------------


def test_generate_invoice_number_uses_select_for_update():
    """Source-inspection canary: both generate_invoice_number methods must contain
    select_for_update() and transaction.atomic to prevent accidental regression.
    """
    src_invoice = inspect.getsource(Invoice.generate_invoice_number)
    src_student = inspect.getsource(StudentInvoice.generate_invoice_number)

    assert "select_for_update" in src_invoice, (
        "Invoice.generate_invoice_number must use select_for_update() to prevent races"
    )
    assert "select_for_update" in src_student, (
        "StudentInvoice.generate_invoice_number must use select_for_update() to prevent races"
    )
    assert "transaction.atomic" in src_invoice, (
        "Invoice.generate_invoice_number must use transaction.atomic() to prevent races"
    )
    assert "transaction.atomic" in src_student, (
        "StudentInvoice.generate_invoice_number must use transaction.atomic() to prevent races"
    )
