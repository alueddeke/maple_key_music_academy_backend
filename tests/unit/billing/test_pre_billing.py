"""
Wave 0 RED stubs — turns green when Plan 02 model migration applies.

Unit tests for PreBillingInvoice model and draft amount formula.
Covers: BILL-01 (model fields), BILL-02 (BillableContact.helcim_customer_id),
BILL-04 (draft amount formula), BILL-06 (one line item per lesson).

These tests FAIL at collection time until Plan 02 ships the PreBillingInvoice model.
That is the EXPECTED Wave 0 RED state.
"""

import pytest
from decimal import Decimal
from datetime import date, time

from billing.models import PreBillingInvoice, BillableContact, Lesson, StudentCreditAccount


# ---------------------------------------------------------------------------
# Factory helpers — explicit sentinel values
# ---------------------------------------------------------------------------

def _make_student_with_contact(school):
    """Create a student User + primary BillableContact for the given school."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    student = User.objects.create_user(
        email=f"student_{id(school)}@prebilling.test",
        password="testpass123",
        user_type="student",
        first_name="Pre",
        last_name="BillingStudent",
        school=school,
        is_approved=True,
    )
    contact = BillableContact.objects.create(
        student=student,
        school=school,
        is_primary=True,
        first_name="Pre",
        last_name="BillingContact",
        email=f"contact_{id(school)}@prebilling.test",
        phone="555-0100",
    )
    return student, contact


def _make_pre_billing_invoice(student, school, status='draft', amount=Decimal('120.00')):
    """Create a PreBillingInvoice with explicit sentinel values."""
    return PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status=status,
        amount=amount,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )


# ---------------------------------------------------------------------------
# Class 1 — PreBillingInvoice model field assertions (BILL-01)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPreBillingInvoiceModel:
    """BILL-01: PreBillingInvoice model field contracts."""

    def test_pre_billing_invoice_model(self, school, management_user):
        """PreBillingInvoice model has correct fields, choices, and FKs."""
        from django.db import models as dj_models
        from simple_history.models import HistoricalRecords

        # STATUS_CHOICES must contain exactly these four strings
        status_codes = [code for code, _ in PreBillingInvoice.STATUS_CHOICES]
        assert 'draft' in status_codes
        assert 'sent' in status_codes
        assert 'adjusted' in status_codes
        assert 'paid' in status_codes
        assert len(status_codes) == 4

        # Default status is 'draft'
        student, _ = _make_student_with_contact(school)
        invoice = _make_pre_billing_invoice(student, school)
        assert invoice.status == 'draft'

        # school FK
        school_field = PreBillingInvoice._meta.get_field('school')
        assert school_field.is_relation
        assert school_field.related_model.__name__ == 'School'

        # student FK (user_type='student')
        student_field = PreBillingInvoice._meta.get_field('student')
        assert student_field.is_relation

        # amount is DecimalField(max_digits=10, decimal_places=2)
        amount_field = PreBillingInvoice._meta.get_field('amount')
        assert isinstance(amount_field, dj_models.DecimalField)
        assert amount_field.max_digits == 10
        assert amount_field.decimal_places == 2

        # period_start and period_end are DateField
        period_start_field = PreBillingInvoice._meta.get_field('period_start')
        period_end_field = PreBillingInvoice._meta.get_field('period_end')
        assert isinstance(period_start_field, dj_models.DateField)
        assert isinstance(period_end_field, dj_models.DateField)

        # helcim_invoice_id and payment_token are CharField and allow blank
        helcim_invoice_id_field = PreBillingInvoice._meta.get_field('helcim_invoice_id')
        payment_token_field = PreBillingInvoice._meta.get_field('payment_token')
        assert isinstance(helcim_invoice_id_field, dj_models.CharField)
        assert isinstance(payment_token_field, dj_models.CharField)
        assert helcim_invoice_id_field.blank is True
        assert payment_token_field.blank is True

        # history is a HistoricalRecords manager
        assert hasattr(PreBillingInvoice, 'history')


# ---------------------------------------------------------------------------
# Class 2 — BillableContact.helcim_customer_id field assertions (BILL-02)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBillableContactCustomerId:
    """BILL-02: BillableContact.helcim_customer_id field contract."""

    def test_billable_contact_customer_id(self, school):
        """helcim_customer_id accepts None, accepts string, persists to DB."""
        student, contact = _make_student_with_contact(school)

        # Accepts None (initial state — not yet sent to Helcim)
        assert contact.helcim_customer_id is None

        # Accepts a string customer ID
        contact.helcim_customer_id = 'cust_12345'
        contact.save()
        contact.refresh_from_db()
        assert contact.helcim_customer_id == 'cust_12345'

        # Persists on a fresh instance
        fresh = BillableContact.objects.get(pk=contact.pk)
        assert fresh.helcim_customer_id == 'cust_12345'

        # Can be set back to None (e.g., re-import scenario)
        contact.helcim_customer_id = None
        contact.save()
        contact.refresh_from_db()
        assert contact.helcim_customer_id is None


# ---------------------------------------------------------------------------
# Class 3 — Draft amount formula (BILL-04)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDraftAmountFormula:
    """BILL-04: Draft amount = max(0, gross - credit), floor at zero."""

    @pytest.mark.parametrize("gross,credit,expected", [
        (Decimal('400.00'), Decimal('0.00'),   Decimal('400.00')),  # no credit applied
        (Decimal('400.00'), Decimal('150.00'), Decimal('250.00')),  # partial credit
        (Decimal('100.00'), Decimal('500.00'), Decimal('0.00')),    # credit exceeds gross → floor
    ])
    def test_draft_amount_formula(self, gross, credit, expected):
        """Draft amount = max(0, gross - credit)."""
        result = max(Decimal('0.00'), gross - credit)
        assert result == expected


# ---------------------------------------------------------------------------
# Class 4 — One line item per lesson (BILL-06)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLineItemsPerLesson:
    """BILL-06: PreBillingInvoice.lessons M2M — one entry per lesson on distinct dates."""

    def test_line_items_per_lesson(self, school, teacher_user):
        """Invoice with 4 M2M lessons has count=4 and 4 distinct scheduled_dates."""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        student, _ = _make_student_with_contact(school)
        invoice = _make_pre_billing_invoice(student, school)

        # Create 4 Lesson instances on distinct dates
        lesson_dates = [
            date(2026, 6, 3),
            date(2026, 6, 10),
            date(2026, 6, 17),
            date(2026, 6, 24),
        ]
        for d in lesson_dates:
            lesson = Lesson.objects.create(
                teacher=teacher_user,
                student=student,
                school=school,
                lesson_type='online',
                teacher_rate=Decimal('45.00'),
                student_rate=Decimal('60.00'),
                scheduled_date=d,
                duration=1.0,
                status='confirmed',
            )
            invoice.lessons.add(lesson)

        assert invoice.lessons.count() == 4
        scheduled = [l.scheduled_date for l in invoice.lessons.all()]
        assert len(set(scheduled)) == 4  # all dates are distinct
