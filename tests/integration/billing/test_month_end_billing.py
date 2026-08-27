"""
Integration tests for Phase 22 month-end billing endpoints.

Requirements covered:
  - ADJ-01: Teacher can PATCH BatchLessonItem status on approved batches (no batch Invoice yet)
  - ADJ-03: Future lessons reject completed/forfeited with 400
  - ADJ-05: management_generate_teacher_invoice sums completed+forfeited for Invoice total
  - ADJ-06: waived_rollover CreditTransactions written at Invoice generation (not at approval)
  - ADJ-07: Teacher PATCH rejected once batch.invoice is set (locked)
  - ADJ-09: management_month_end_queue returns only approved batches without Invoice

These tests are intentionally RED — they reference URL names and behavior that do not
exist until Plans 02-03 in Phase 22. They are Wave 0 stubs that define contracts for
implementation. They MUST fail now (NoReverseMatch or assertion failure); that is the
expected RED state.
"""

import pytest
from decimal import Decimal
from datetime import date, time, timedelta
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

from billing.models import (
    MonthlyInvoiceBatch,
    BatchLessonItem,
    Invoice,
    StudentCreditAccount,
    CreditTransaction,
    BillableContact,
    StudentInvoice,
)

User = get_user_model()


@pytest.fixture
def management_client(management_user):
    """Separate APIClient instance authenticated as management_user."""
    client = APIClient()
    client.force_authenticate(user=management_user)
    return client


@pytest.fixture
def teacher_client(teacher_user):
    """Separate APIClient instance authenticated as teacher_user."""
    client = APIClient()
    client.force_authenticate(user=teacher_user)
    return client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_approved_batch(teacher, school, month=6, year=2026):
    """Create a MonthlyInvoiceBatch already in 'approved' status."""
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher,
        school=school,
        month=month,
        year=year,
        status='approved',
    )
    return batch


def _make_item(batch, student, scheduled_date=None, status='completed',
               teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'),
               duration=Decimal('1.0')):
    """Create a BatchLessonItem attached to a batch."""
    if scheduled_date is None:
        scheduled_date = date(2026, 6, 1)
    return BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=scheduled_date,
        start_time=time(10, 0),
        duration=duration,
        lesson_type='online',
        teacher_rate=teacher_rate,
        student_rate=student_rate,
        status=status,
    )


def _make_student_invoice(batch, student, school, items):
    """Create the approval-time StudentInvoice containing `items` (the charged set).

    Membership in StudentInvoice.lesson_items is what marks an item as charged at
    approval — generation only writes waived_rollover credits for member items.
    """
    si = StudentInvoice.objects.create(
        batch=batch,
        student=student,
        school=school,
        amount=Decimal('0.00'),
        billing_contact_name='Test Contact',
        billing_email='contact@example.com',
        billing_phone='555-0100',
        billing_street_address='1 Test St',
        billing_city='Toronto',
        billing_province='ON',
        billing_postal_code='M1M1M1',
    )
    si.lesson_items.set(items)
    si.amount = si.calculate_amount()
    si.save(update_fields=['amount'])
    return si


def _make_invoice(school, teacher, total_amount=Decimal('0.00'), management_user=None):
    """Create an Invoice of type teacher_payment (used to set batch.invoice = locked)."""
    return Invoice.objects.create(
        invoice_type='teacher_payment',
        teacher=teacher,
        school=school,
        status='pending',
        total_amount=total_amount,
        payment_balance=total_amount,
        created_by=management_user,
    )


# ---------------------------------------------------------------------------
# Class 1 — Teacher adjustment endpoint (ADJ-01, ADJ-03, ADJ-07)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTeacherAdjustmentEndpoint:
    """ADJ-01, ADJ-03, ADJ-07: teacher_batch_adjustment_item endpoint."""

    def test_teacher_can_mark_exception_on_approved_batch(
        self, teacher_client, teacher_user, student_user, school, school_settings
    ):
        """
        ADJ-01: PATCH on an approved batch (batch.invoice is None) with a past-dated item
        saves the new status immediately and returns 200.

        RED: NoReverseMatch until Plan 02 adds the URL + view.
        """
        batch = _make_approved_batch(teacher_user, school)
        item = _make_item(batch, student_user, scheduled_date=date(2026, 6, 1), status='completed')

        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = teacher_client.patch(
            url,
            {'status': 'waived', 'cancellation_reason': 'Teacher cancelled'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.status == 'waived'

    def test_teacher_cannot_adjust_unapproved_batch(
        self, teacher_client, teacher_user, student_user, school, school_settings
    ):
        """
        ADJ-01: PATCH on a batch with status='submitted' is rejected with 400.

        RED: NoReverseMatch until Plan 02 adds the URL + view.
        """
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=6, year=2026, status='submitted'
        )
        item = _make_item(batch, student_user, scheduled_date=date(2026, 6, 1))

        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = teacher_client.patch(url, {'status': 'waived'}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_future_lesson_rejects_completed_status(
        self, teacher_client, teacher_user, student_user, school, school_settings
    ):
        """
        ADJ-03: PATCH with status='completed' on an item whose scheduled_date is tomorrow
        must return 400.

        RED: NoReverseMatch until Plan 02 adds the URL + view.
        """
        batch = _make_approved_batch(teacher_user, school)
        tomorrow = date.today() + timedelta(days=1)
        item = _make_item(batch, student_user, scheduled_date=tomorrow, status='confirmed')

        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = teacher_client.patch(url, {'status': 'completed'}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_teacher_adjustment_blocked_after_invoice_generated(
        self, teacher_client, teacher_user, student_user, school, school_settings, management_user
    ):
        """
        ADJ-07: PATCH on a batch whose batch.invoice is already set (Invoice generated)
        must return 400 -- the batch is locked.

        RED: NoReverseMatch until Plan 02 adds the URL + view.
        """
        batch = _make_approved_batch(teacher_user, school)
        item = _make_item(batch, student_user, scheduled_date=date(2026, 6, 1), status='completed')

        # Simulate Invoice already generated: set batch.invoice FK
        invoice = _make_invoice(school, teacher_user, management_user=management_user)
        batch.invoice = invoice
        batch.save(update_fields=['invoice'])

        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = teacher_client.patch(url, {'status': 'waived'}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# Class 2 -- Generate teacher invoice endpoint (ADJ-05, ADJ-06)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGenerateTeacherInvoiceEndpoint:
    """ADJ-05, ADJ-06: management_generate_teacher_invoice endpoint."""

    def test_generate_teacher_invoice_sums_completed_and_forfeited(
        self, management_client, teacher_user, student_user, school, school_settings, management_user
    ):
        """
        ADJ-05: POST on an approved batch creates an Invoice(invoice_type='teacher_payment')
        with total_amount == sum of (teacher_rate * duration) for completed + forfeited items
        only. Waived and cancelled items are excluded from teacher pay.
        After POST, batch.invoice_id is set.

        RED: NoReverseMatch until Plan 02 adds the URL + view.
        """
        batch = _make_approved_batch(teacher_user, school)

        # 2 completed @ 45.00 x 1.0 = 90.00
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 1), status='completed',
                   teacher_rate=Decimal('45.00'), duration=Decimal('1.0'))
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 8), status='completed',
                   teacher_rate=Decimal('45.00'), duration=Decimal('1.0'))
        # 1 forfeited @ 45.00 x 1.0 = 45.00 (teacher paid for forfeited)
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 15), status='forfeited',
                   teacher_rate=Decimal('45.00'), duration=Decimal('1.0'))
        # 1 waived -- excluded from teacher pay total
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 22), status='waived',
                   teacher_rate=Decimal('45.00'), duration=Decimal('1.0'))
        # 1 cancelled -- excluded from teacher pay total
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 29), status='cancelled',
                   teacher_rate=Decimal('45.00'), duration=Decimal('1.0'))

        url = reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id})

        response = management_client.post(url, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == 'invoice_generated'

        # Invoice total = 2 completed + 1 forfeited = 135.00; waived+cancelled excluded
        expected_total = Decimal('135.00')
        assert Decimal(response.data['total_amount']) == expected_total

        # Invoice record created
        invoice = Invoice.objects.filter(invoice_type='teacher_payment').first()
        assert invoice is not None
        assert invoice.total_amount == expected_total

        # batch.invoice linked
        batch.refresh_from_db()
        assert batch.invoice_id == invoice.id

    def test_generate_writes_waived_credit_transactions(
        self, management_client, teacher_user, student_user, school, school_settings, management_user
    ):
        """
        ADJ-06: POST on an approved batch with waived items that were CHARGED at
        approval (member of StudentInvoice.lesson_items) writes
        CreditTransaction(type='waived_rollover') per waived item and increments
        StudentCreditAccount.balance by lesson_rate (student_rate * duration) per waived item.
        """
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('0.00')
        )
        batch = _make_approved_batch(teacher_user, school)

        # 1 completed (for the batch to have something billable)
        completed = _make_item(batch, student_user, scheduled_date=date(2026, 6, 1), status='completed',
                               teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))
        # 2 waived items charged at approval (post-approval waives) -- each should
        # generate a waived_rollover CreditTransaction
        waived_a = _make_item(batch, student_user, scheduled_date=date(2026, 6, 8), status='waived',
                              teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))
        waived_b = _make_item(batch, student_user, scheduled_date=date(2026, 6, 15), status='waived',
                              teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))
        # Approval-time invoice included all three (the waives happened after approval)
        _make_student_invoice(batch, student_user, school, [completed, waived_a, waived_b])

        url = reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id})

        response = management_client.post(url, format='json')

        assert response.status_code == status.HTTP_200_OK

        # 2 waived_rollover CreditTransactions created (one per waived item)
        assert CreditTransaction.objects.filter(type='waived_rollover').count() == 2

        # Balance incremented by lesson_rate per waived item: 2 * (60.00 * 1.0) = 120.00
        account = StudentCreditAccount.objects.get(student=student_user, school=school)
        assert account.balance == Decimal('120.00')

        # Response includes waived_credits_written count
        assert response.data['waived_credits_written'] == 2

    def test_generate_skips_rollover_for_draft_time_waives(
        self, management_client, teacher_user, student_user, school, school_settings, management_user
    ):
        """
        Regression (2026-08-27): a lesson waived while the batch was still a DRAFT is
        excluded from the approval-time StudentInvoice — the parent was never charged
        for it, so generation must NOT write a waived_rollover credit (that would gift
        a free lesson credit / under-bill the next invoice by one lesson rate).

        Draft-time waive = status 'waived' but NOT a member of StudentInvoice.lesson_items.
        """
        StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('0.00')
        )
        batch = _make_approved_batch(teacher_user, school)

        completed = _make_item(batch, student_user, scheduled_date=date(2026, 6, 1), status='completed',
                               teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))
        # Waived before approval: never invoiced
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 8), status='waived',
                   teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))
        # Waived after approval: was invoiced, deserves the refund
        waived_charged = _make_item(batch, student_user, scheduled_date=date(2026, 6, 15), status='waived',
                                    teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))
        # Approval-time invoice excluded the draft-time waive
        _make_student_invoice(batch, student_user, school, [completed, waived_charged])

        url = reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id})
        response = management_client.post(url, format='json')

        assert response.status_code == status.HTTP_200_OK

        # Only the charged waive is refunded
        assert CreditTransaction.objects.filter(type='waived_rollover').count() == 1
        account = StudentCreditAccount.objects.get(student=student_user, school=school)
        assert account.balance == Decimal('60.00')
        assert response.data['waived_credits_written'] == 1

    def test_generate_pays_teacher_for_confirmed_lessons(
        self, management_client, teacher_user, student_user, school, school_settings, management_user
    ):
        """
        Regression (Bug 1): a normal submitted batch carries DB status 'confirmed'
        (past lessons only DISPLAY as "Completed"). Generation must pay the teacher
        for confirmed lessons — historically it filtered completed+forfeited only,
        producing a $0 teacher invoice for an entirely-confirmed batch.
        """
        batch = _make_approved_batch(teacher_user, school)
        # 3 confirmed @ 45.00 x 1.0 = 135.00
        for d in (1, 8, 15):
            _make_item(batch, student_user, scheduled_date=date(2026, 6, d),
                       status='confirmed', teacher_rate=Decimal('45.00'), duration=Decimal('1.0'))

        url = reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id})
        response = management_client.post(url, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert Decimal(response.data['total_amount']) == Decimal('135.00')

    def test_generate_pays_teacher_for_trial_lessons(
        self, management_client, teacher_user, student_user, school, school_settings, management_user
    ):
        """
        Regression (Bug 7): trial lessons pay the teacher (a business expense to win
        new clients) while the student is charged $0. Generation must include trial
        pay in the teacher invoice total.
        """
        batch = _make_approved_batch(teacher_user, school)
        # 1 completed @ 45.00 + 1 trial @ 45.00 (trial pays teacher, student $0)
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 1), status='completed',
                   teacher_rate=Decimal('45.00'), duration=Decimal('1.0'))
        trial = _make_item(batch, student_user, scheduled_date=date(2026, 6, 8), status='trial',
                           teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'),
                           duration=Decimal('1.0'))

        # trial: teacher paid, student not charged
        assert trial.calculate_teacher_payment() == Decimal('45.00')
        assert trial.calculate_student_charge() == Decimal('0.00')

        url = reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id})
        response = management_client.post(url, format='json')

        assert response.status_code == status.HTTP_200_OK
        # 45 completed + 45 trial = 90.00
        assert Decimal(response.data['total_amount']) == Decimal('90.00')

    def test_generate_writes_forfeited_audit_transaction_without_double_charging(
        self, management_client, teacher_user, student_user, school, school_settings, management_user
    ):
        """
        Regression (Bug 2): a lesson forfeited AFTER approval was already charged to
        the student at approval (as a 'confirmed' decrement). Generation must record
        the no-show with a CreditTransaction(type='forfeited') for the audit trail,
        but must NOT decrement the balance again (no double charge).
        """
        account = StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('500.00')
        )
        batch = _make_approved_batch(teacher_user, school)
        # 1 completed (billable) + 1 forfeited @ student_rate 60 x 1.0 = 60.00 audit row
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 1), status='completed',
                   teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 8), status='forfeited',
                   teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))

        url = reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id})
        response = management_client.post(url, format='json')

        assert response.status_code == status.HTTP_200_OK
        # one forfeited audit row written
        assert response.data['forfeited_credits_written'] == 1
        forfeited_txns = CreditTransaction.objects.filter(type='forfeited', account=account)
        assert forfeited_txns.count() == 1
        assert forfeited_txns.first().amount == Decimal('60.00')
        # balance unchanged — the charge happened at approval, not again here
        account.refresh_from_db()
        assert account.balance == Decimal('500.00')

    def test_generate_is_dedup_safe_for_forfeited_audit_rows(
        self, management_client, teacher_user, student_user, school, school_settings, management_user
    ):
        """
        A lesson forfeited BEFORE approval already carries a 'forfeited' row written
        at approval. Generation must not write a second one for the same charge.
        """
        account = StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('100.00')
        )
        batch = _make_approved_batch(teacher_user, school)
        _make_item(batch, student_user, scheduled_date=date(2026, 6, 1), status='forfeited',
                   teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))
        # Simulate the approval-time forfeited row already existing
        CreditTransaction.objects.create(
            account=account, school=school, type='forfeited', amount=Decimal('60.00')
        )

        url = reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id})
        response = management_client.post(url, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['forfeited_credits_written'] == 0
        assert CreditTransaction.objects.filter(type='forfeited', account=account).count() == 1


# ---------------------------------------------------------------------------
# Class 3 -- Month-end queue endpoint (ADJ-09)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMonthEndQueueEndpoint:
    """ADJ-09: management_month_end_queue endpoint."""

    def test_month_end_queue_excludes_invoiced_batches(
        self, management_client, teacher_user, student_user, school, school_settings, management_user
    ):
        """
        ADJ-09: GET management_month_end_queue returns only approved batches where
        batch.invoice IS NULL. Batches that already have an Invoice linked are excluded.

        RED: NoReverseMatch until Plan 02 adds the URL + view.
        """
        # Batch 1: approved, invoice NOT set -- should appear in queue
        batch_no_invoice = _make_approved_batch(teacher_user, school, month=6, year=2026)

        # Batch 2: approved, invoice SET -- must NOT appear in queue
        batch_with_invoice = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=5, year=2026, status='approved'
        )
        invoice = _make_invoice(school, teacher_user, management_user=management_user)
        batch_with_invoice.invoice = invoice
        batch_with_invoice.save(update_fields=['invoice'])

        url = reverse('management_month_end_queue')

        response = management_client.get(url)

        assert response.status_code == status.HTTP_200_OK

        returned_ids = [b['id'] for b in response.data]
        assert batch_no_invoice.id in returned_ids
        assert batch_with_invoice.id not in returned_ids
