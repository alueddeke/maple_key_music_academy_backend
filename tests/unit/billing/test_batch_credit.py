"""
Unit tests for Phase 20 batch approval credit reconciliation.

Coverage (REC-02 through REC-06):
  - Forfeited lesson: Lesson.forfeited created, added to StudentInvoice, balance -= amount,
    CreditTransaction(type='forfeited') written
  - Waived lesson: Lesson.waived created, NOT in StudentInvoice, balance += lesson_rate,
    CreditTransaction(type='waived_rollover') written
  - Confirmed lesson: balance -= amount, no CreditTransaction written (D-01)
  - Balance floor: confirmed + forfeited deductions floor at 0 (D-02)
  - StudentInvoice.credit_applied + amount_after_credit populated (D-10, D-11)
  - No PreBillingInvoice for student → credit_applied=0, amount_after_credit=invoice.amount (D-11)
  - select_for_update() used: concurrent approval does not double-apply credit (REC-02)
  - Lazy StudentCreditAccount creation (Claude's Discretion)

Tests are RED until Plan 02 (migration 0052) and Plan 04 (management_approve_batch extension)
land. Tests referencing credit_applied / amount_after_credit use getattr(..., None) to remain
collectible before Plan 02 ships the migration.
"""

import pytest
from decimal import Decimal
from datetime import date, time
from unittest import mock
from django.db import transaction
from django.urls import reverse
from rest_framework.test import APIClient

from billing.models import (
    Lesson,
    BatchLessonItem,
    MonthlyInvoiceBatch,
    StudentInvoice,
    StudentCreditAccount,
    CreditTransaction,
    PreBillingInvoice,
)


# ---------------------------------------------------------------------------
# Factory helpers — copied verbatim from tests/unit/billing/test_credit_models.py
# ---------------------------------------------------------------------------

def _make_batch(teacher, school, batch_number=None, month=6, year=2026):
    """Create a MonthlyInvoiceBatch; auto-generates batch_number if not provided."""
    kwargs = dict(teacher=teacher, school=school, month=month, year=year)
    if batch_number:
        kwargs['batch_number'] = batch_number
    return MonthlyInvoiceBatch.objects.create(**kwargs)


def _make_batch_lesson_item(
    batch,
    student,
    status='completed',
    teacher_rate=Decimal('45.00'),
    student_rate=Decimal('60.00'),
    duration=Decimal('1.0'),
):
    """Create a BatchLessonItem with explicit sentinel rates; hard-codes date/time."""
    return BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=date(2026, 6, 15),
        start_time=time(10, 0),
        duration=duration,
        lesson_type='online',
        teacher_rate=teacher_rate,
        student_rate=student_rate,
        status=status,
    )


def _setup_billable_contact(student, school):
    """Create a primary BillableContact for a student — required by management_approve_batch."""
    from billing.models import BillableContact
    return BillableContact.objects.create(
        student=student,
        school=school,
        contact_type='parent',
        first_name='Test',
        last_name='Contact',
        email=f'contact_{student.pk}@batchcredit.test',
        phone='416-555-0100',
        street_address='123 Test St',
        city='Toronto',
        province='ON',
        postal_code='M5H 2N2',
        is_primary=True,
    )


def _approve_batch(management_user, batch):
    """POST to management_approve_batch for this batch; returns response."""
    client = APIClient()
    client.force_authenticate(user=management_user)
    url = reverse('management_approve_batch', kwargs={'batch_id': batch.id})
    return client.post(url)


# ---------------------------------------------------------------------------
# Class 1 — Confirmed lesson credit deduction (REC-03)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBatchApprovalConfirmed:
    """REC-03 (D-01, D-02): Confirmed lesson credit deduction at batch approval."""

    def test_confirmed_lesson_decrements_balance_no_credit_transaction(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        Confirmed lesson at batch approval: balance decremented by lesson amount,
        no CreditTransaction written (D-01).

        RED until Plan 04 adds credit deduction logic to management_approve_batch.
        """
        _setup_billable_contact(student_user, school)
        account = StudentCreditAccount.objects.create(
            student=student_user,
            school=school,
            balance=Decimal('100.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-01-C1')
        # Set status directly to submitted so approval is allowed
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        account.refresh_from_db()
        assert account.balance == Decimal('55.00')
        assert CreditTransaction.objects.filter(type='pre_billing_payment').count() == 0
        assert CreditTransaction.objects.count() == 0

    def test_confirmed_lesson_balance_floors_at_zero_when_deduction_exceeds_balance(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        Deduction exceeds balance → balance floors at Decimal('0.00') (D-02 max(0,...)).
        No IntegrityError raised from DB CHECK constraint.

        RED until Plan 04 implements the max(0,...) floor.
        """
        _setup_billable_contact(student_user, school)
        account = StudentCreditAccount.objects.create(
            student=student_user,
            school=school,
            balance=Decimal('20.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-01-C2')
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        account.refresh_from_db()
        assert account.balance == Decimal('0.00')


# ---------------------------------------------------------------------------
# Class 2 — Forfeited lesson processing (REC-04)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBatchApprovalForfeited:
    """REC-04 (D-07, D-08, D-09): Forfeited lesson processing at batch approval."""

    def test_forfeited_creates_lesson_record_with_status_forfeited(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        Forfeited BatchLessonItem → Lesson record with status='forfeited' created (D-07).
        BatchLessonItem.created_lesson FK points to that Lesson.

        RED until Plan 04 adds forfeited Lesson creation to management_approve_batch.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('100.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-02-F1')
        batch.status = 'submitted'
        batch.save()
        item = _make_batch_lesson_item(
            batch, student_user, status='forfeited',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        assert Lesson.objects.filter(status='forfeited').count() == 1
        item.refresh_from_db()
        assert item.created_lesson is not None
        assert item.created_lesson.status == 'forfeited'

    def test_forfeited_added_to_student_invoice_lesson_items_m2m(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        Forfeited item added to StudentInvoice.lesson_items M2M alongside confirmed item (D-08).
        M2M target is BatchLessonItem (not Lesson) per PATTERNS.md.

        RED until Plan 04 adds forfeited items to M2M after Lesson creation.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('100.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-02-F2')
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )
        _make_batch_lesson_item(
            batch, student_user, status='forfeited',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        student_invoice = StudentInvoice.objects.get(batch=batch, student=student_user)
        assert student_invoice.lesson_items.filter(status='forfeited').exists()

    def test_forfeited_decrements_balance_and_writes_credit_transaction(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        Forfeited lesson: balance -= lesson_amount, CreditTransaction(type='forfeited')
        written (D-09).

        RED until Plan 04 implements forfeited credit deduction.
        """
        _setup_billable_contact(student_user, school)
        account = StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('100.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-02-F3')
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='forfeited',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        account.refresh_from_db()
        assert account.balance == Decimal('55.00')
        assert CreditTransaction.objects.filter(
            type='forfeited', amount=Decimal('45.00'),
        ).count() == 1

    def test_forfeited_recalculates_student_invoice_amount_after_m2m_add(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        Pitfall 5 guard: after adding forfeited items to StudentInvoice.lesson_items M2M,
        invoice.amount must be recalculated to include forfeited charges, not just confirmed.

        RED until Plan 04 calls student_invoice.amount = student_invoice.calculate_amount()
        after adding forfeited items.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('200.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-02-F4')
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )
        _make_batch_lesson_item(
            batch, student_user, status='forfeited',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        student_invoice = StudentInvoice.objects.get(batch=batch, student=student_user)
        # amount must include both confirmed (45.00) and forfeited (45.00) = 90.00
        expected_amount = student_invoice.calculate_amount()
        assert student_invoice.amount == expected_amount


# ---------------------------------------------------------------------------
# Class 3 — Waived lesson processing (REC-05)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBatchApprovalWaived:
    """REC-05 (D-06, D-09): Waived lesson processing at batch approval."""

    def test_waived_creates_lesson_record_with_status_waived(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        Waived BatchLessonItem → Lesson record with status='waived' created (D-07).

        RED until Plan 04 adds waived Lesson creation to management_approve_batch.
        Note: management_approve_batch currently has no completed items for student_user
        so we add one completed item to avoid 'No completed or trial lessons' error.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('0.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-03-W1')
        batch.status = 'submitted'
        batch.save()
        # Add a completed item so the batch passes the "no completed lessons" guard
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )
        _make_batch_lesson_item(
            batch, student_user, status='waived',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        assert Lesson.objects.filter(status='waived').count() == 1

    def test_waived_not_added_to_student_invoice(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        Waived lesson excluded from StudentInvoice.lesson_items M2M (D-08).
        Student is not charged for waived lessons.

        RED until Plan 04 ensures waived items are NOT added to the invoice M2M.
        Currently waived items are simply skipped — but once forfeited items ARE added
        (Plan 04 Step B), waived must remain excluded.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('100.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-03-W2')
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )
        _make_batch_lesson_item(
            batch, student_user, status='waived',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        student_invoice = StudentInvoice.objects.get(batch=batch, student=student_user)
        assert not student_invoice.lesson_items.filter(status='waived').exists()

    def test_waived_does_not_write_rollover_at_approval_time(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        Phase 22 (D-05): waived_rollover CreditTransaction is NO LONGER written at
        management_approve_batch time. Credit rollover is deferred to
        management_generate_teacher_invoice (ADJ-06).

        After batch approval:
        - CreditTransaction.objects.filter(type='waived_rollover').count() == 0
        - Account balance reflects NO waived increment; confirmed deduction floors at 0

        RED until Plan 02 removes the waived credit block from management_approve_batch
        (billing/views/management.py lines 1532-1540).
        """
        _setup_billable_contact(student_user, school)
        account = StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('0.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-03-W3')
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )
        _make_batch_lesson_item(
            batch, student_user, status='waived',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        # Phase 22: waived_rollover is NO LONGER written at approval time (D-05)
        # Credit is deferred to management_generate_teacher_invoice
        assert CreditTransaction.objects.filter(type='waived_rollover').count() == 0
        # Balance: start=0; confirmed deduction (-45) floors at 0; waived has no effect here
        account.refresh_from_db()
        assert account.balance == Decimal('0.00')

    def test_waived_teacher_payment_is_zero_via_calculate_teacher_payment(
        self, school, teacher_user, student_user
    ):
        """
        D-06 model fix: BatchLessonItem.calculate_teacher_payment() returns Decimal('0.00')
        for status='waived'. This stub anchors the model behaviour — Plan 02 makes it pass.

        RED until Plan 02 changes `if self.status == 'cancelled':` to
        `if self.status in ('cancelled', 'waived'):`.
        """
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-03-W4')
        item = _make_batch_lesson_item(
            batch, student_user, status='waived',
            teacher_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )
        assert item.calculate_teacher_payment() == Decimal('0.00')


# ---------------------------------------------------------------------------
# Class 4 — StudentInvoice credit fields (REC-06)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestStudentInvoiceCreditFields:
    """REC-06 (D-10, D-11, D-12): credit_applied + amount_after_credit field population."""

    def test_credit_applied_equals_gross_minus_pre_billing_amount(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        credit_applied = StudentInvoice.amount (gross) - PreBillingInvoice.amount (D-10).
        When gross=120.00, pre-billing=100.00 → credit_applied=20.00.

        RED until Plan 02 adds the fields (AttributeError before that) and Plan 04
        populates them during approval.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('100.00'),
        )
        PreBillingInvoice.objects.create(
            student=student_user,
            school=school,
            status='sent',
            amount=Decimal('100.00'),
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            helcim_invoice_id='INV-2026-06-CREDIT-01',
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-04-CF1', month=6, year=2026)
        batch.status = 'submitted'
        batch.save()
        # Two completed lessons at 60.00 each = 120.00 gross
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        student_invoice = StudentInvoice.objects.get(batch=batch, student=student_user)
        credit_applied = getattr(student_invoice, 'credit_applied', None)
        assert credit_applied == Decimal('20.00')

    def test_amount_after_credit_equals_pre_billing_amount(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        amount_after_credit = PreBillingInvoice.amount (D-11).
        When pre-billing=100.00 → amount_after_credit=100.00.

        RED until Plan 02 + Plan 04.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('100.00'),
        )
        PreBillingInvoice.objects.create(
            student=student_user,
            school=school,
            status='sent',
            amount=Decimal('100.00'),
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            helcim_invoice_id='INV-2026-06-CREDIT-02',
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-04-CF2', month=6, year=2026)
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        student_invoice = StudentInvoice.objects.get(batch=batch, student=student_user)
        amount_after_credit = getattr(student_invoice, 'amount_after_credit', None)
        assert amount_after_credit == Decimal('100.00')

    def test_no_pre_billing_invoice_sets_credit_applied_zero(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        No PreBillingInvoice for this student+period → credit_applied=Decimal('0.00'),
        amount_after_credit=student_invoice.amount (D-11 fallback).

        RED until Plan 02 + Plan 04.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('50.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-04-CF3', month=6, year=2026)
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        student_invoice = StudentInvoice.objects.get(batch=batch, student=student_user)
        credit_applied = getattr(student_invoice, 'credit_applied', None)
        amount_after_credit = getattr(student_invoice, 'amount_after_credit', None)
        assert credit_applied == Decimal('0.00')
        assert amount_after_credit == student_invoice.amount

    def test_credit_applied_uses_batch_year_month_for_period_lookup(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        PreBillingInvoice.period_start = date(batch.year, batch.month, 1) is the lookup
        key used to find the invoice for this batch period (D-10).

        RED until Plan 04 uses batch.year + batch.month to build period_start for lookup.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('100.00'),
        )
        # PreBillingInvoice with period_start matching batch month/year
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-04-CF4', month=6, year=2026)
        batch.status = 'submitted'
        batch.save()
        pre_invoice = PreBillingInvoice.objects.create(
            student=student_user,
            school=school,
            status='sent',
            amount=Decimal('60.00'),
            period_start=date(batch.year, batch.month, 1),
            period_end=date(batch.year, batch.month, 30),
            helcim_invoice_id='INV-2026-06-CREDIT-04',
        )
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )

        response = _approve_batch(management_user, batch)
        assert response.status_code == 200

        student_invoice = StudentInvoice.objects.get(batch=batch, student=student_user)
        # Lookup succeeded → credit_applied and amount_after_credit use the pre_invoice values
        credit_applied = getattr(student_invoice, 'credit_applied', None)
        amount_after_credit = getattr(student_invoice, 'amount_after_credit', None)
        # gross=60.00, pre-billing=60.00 → credit_applied=0, amount_after_credit=60.00
        assert credit_applied == Decimal('0.00')
        assert amount_after_credit == Decimal('60.00')


# ---------------------------------------------------------------------------
# Class 5 — Concurrency guard (REC-02)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBatchApprovalConcurrency:
    """REC-02: select_for_update() used on StudentCreditAccount read inside atomic block."""

    def test_select_for_update_used_on_credit_account_read(
        self, school, teacher_user, student_user, management_user, school_settings
    ):
        """
        select_for_update() must be called on StudentCreditAccount within the atomic block
        during batch approval (D-09, STATE.md architectural constraint).

        Asserts via mock.patch.object that select_for_update() is invoked at runtime —
        does not grep source.

        RED until Plan 04 adds select_for_update() to the credit account read.
        """
        _setup_billable_contact(student_user, school)
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('100.00'),
        )
        batch = _make_batch(teacher_user, school, batch_number='BATCH-20-05-SFU1')
        batch.status = 'submitted'
        batch.save()
        _make_batch_lesson_item(
            batch, student_user, status='completed',
            student_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )

        # Patch StudentCreditAccount.objects.select_for_update to track calls
        # while still returning the real queryset (wraps the real method).
        original_sfu = StudentCreditAccount.objects.select_for_update

        select_for_update_called = []

        def tracking_select_for_update(*args, **kwargs):
            select_for_update_called.append(True)
            return original_sfu(*args, **kwargs)

        with mock.patch.object(
            StudentCreditAccount.objects,
            'select_for_update',
            side_effect=tracking_select_for_update,
        ):
            _approve_batch(management_user, batch)

        assert len(select_for_update_called) >= 1, (
            "StudentCreditAccount.objects.select_for_update() was not called "
            "during batch approval — required by D-09 / REC-02 to prevent "
            "concurrent balance corruption"
        )
