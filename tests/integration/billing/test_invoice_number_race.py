"""
Integration tests for invoice number generation race condition.

Tests verify that concurrent save() calls produce distinct, unique invoice numbers.
The advisory lock in generate_invoice_number() must be held until the INSERT commits —
this only holds when save() wraps generate_invoice_number() + super().save() in an
outer transaction.atomic(). Tests call save() (not generate_invoice_number() directly)
to exercise the actual production code path.
"""

import inspect
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from billing.models import Invoice, MonthlyInvoiceBatch, StudentInvoice
from datetime import datetime

User = get_user_model()


# ---------------------------------------------------------------------------
# Test 1 — Invoice concurrent save
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_invoice_number_generation_produces_unique_numbers(school, management_user):
    """Two concurrent Invoice.save() calls must produce distinct invoice numbers.

    Uses a real save() so the advisory lock in generate_invoice_number() is held
    until the INSERT commits — the only scenario where serialization is guaranteed.
    """
    school_id = school.id
    user_id = management_user.id

    def _save():
        connection.close()
        from billing.models import School
        _school = School.objects.get(id=school_id)
        _user = User.objects.get(id=user_id)
        inv = Invoice(
            school=_school,
            invoice_type="teacher_payment",
            payment_balance=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            created_by=_user,
        )
        inv.save()
        return inv.invoice_number

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_save), ex.submit(_save)]
        results = [f.result(timeout=10) for f in futures]

    assert results[0] != results[1], (
        f"Race condition: both threads returned the same invoice number {results[0]}"
    )


# ---------------------------------------------------------------------------
# Test 2 — StudentInvoice concurrent save
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_student_invoice_number_generation_produces_unique_numbers(
    school, teacher_user, management_user
):
    """Two concurrent StudentInvoice.save() calls for the same batch + student
    must produce distinct invoice_number values.
    """
    today = datetime.now()

    # Two students — unique_together(batch, student) prevents two invoices for the same student
    student_a = User.objects.create_user(
        email="race_student_a@test.com", password="testpass123",
        user_type="student", first_name="Race", last_name="StudentA",
        school=school, is_approved=True,
    )
    student_b = User.objects.create_user(
        email="race_student_b@test.com", password="testpass123",
        user_type="student", first_name="Race", last_name="StudentB",
        school=school, is_approved=True,
    )

    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user, school=school,
        month=today.month, year=today.year,
    )

    batch_id = batch.id
    student_a_id = student_a.id
    student_b_id = student_b.id
    school_id = school.id

    def _save(sid):
        connection.close()
        _batch = MonthlyInvoiceBatch.objects.get(id=batch_id)
        _student = User.objects.get(id=sid)
        from billing.models import School
        _school = School.objects.get(id=school_id)
        inv = StudentInvoice(
            batch=_batch, student=_student, school=_school,
            amount=Decimal("0.00"),
            billing_contact_name="Race Student",
            billing_email=f"race{sid}@test.com",
            billing_phone="4165551234",
            billing_street_address="1 Race St",
            billing_city="Toronto", billing_province="ON",
            billing_postal_code="M5H 2N2",
        )
        inv.save()
        return inv.invoice_number

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_save, student_a_id), ex.submit(_save, student_b_id)]
        results = [f.result(timeout=10) for f in futures]

    assert results[0] != results[1], (
        f"Race condition: both threads returned the same student invoice number {results[0]}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Static source inspection canary
# ---------------------------------------------------------------------------


def test_generate_invoice_number_uses_advisory_lock():
    """Source-inspection canary: both generate_invoice_number methods must use
    pg_advisory_xact_lock and transaction.atomic to prevent accidental regression.
    """
    src_invoice = inspect.getsource(Invoice.generate_invoice_number)
    src_student = inspect.getsource(StudentInvoice.generate_invoice_number)

    assert "pg_advisory_xact_lock" in src_invoice, (
        "Invoice.generate_invoice_number must use pg_advisory_xact_lock() to prevent races"
    )
    assert "pg_advisory_xact_lock" in src_student, (
        "StudentInvoice.generate_invoice_number must use pg_advisory_xact_lock() to prevent races"
    )
    assert "transaction.atomic" in src_invoice, (
        "Invoice.generate_invoice_number must use transaction.atomic() to prevent races"
    )
    assert "transaction.atomic" in src_student, (
        "StudentInvoice.generate_invoice_number must use transaction.atomic() to prevent races"
    )
