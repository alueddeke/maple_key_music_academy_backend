"""
Wave 0 RED stubs — turns green when Plans 02-04 land the model, endpoints, and URLs.

Integration test stubs for Pre-Billing Invoice API endpoints.
Covers BILL-03 (generate), BILL-05 (send), BILL-07 (send-all),
BILL-08 (remove-lesson), BILL-09 (void failure).

Tests FAIL at collection time (ImportError: PreBillingInvoice does not exist)
— expected RED state until Plan 02 ships the model.

Mocked Helcim HTTP patterns follow test_helcim_client.py approach
(patch billing.services.helcim_client.requests).
"""

import pytest
from decimal import Decimal
from datetime import date, time
from unittest.mock import patch, Mock

from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from billing.models import (
    PreBillingInvoice,
    BillableContact,
    Lesson,
    RecurringLessonsSchedule,
    StudentCreditAccount,
    CreditTransaction,
    MonthlyInvoiceBatch,
    BatchLessonItem,
)
from billing.services.helcim_client import HelcimAPIError

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
def student_with_contact(school, teacher_user, db):
    """Active student with a primary BillableContact — ready for billing."""
    student = User.objects.create_user(
        email="billing_student@prebilling.test",
        password="testpass123",
        user_type="student",
        first_name="Billing",
        last_name="Student",
        school=school,
        is_approved=True,
    )
    contact = BillableContact.objects.create(
        student=student,
        school=school,
        is_primary=True,
        first_name="Billing",
        last_name="Contact",
        email="billing_contact@prebilling.test",
        phone="555-0200",
        street_address="123 Test St",
        city="Toronto",
        province="ON",
        postal_code="M5H 2N2",
    )
    return student, contact


def _make_confirmed_lesson(student, teacher, school, lesson_date=None):
    """Create a confirmed Lesson for billing draft generation."""
    from django.utils import timezone
    return Lesson.objects.create(
        teacher=teacher,
        student=student,
        school=school,
        lesson_type='online',
        teacher_rate=Decimal('45.00'),
        student_rate=Decimal('60.00'),
        scheduled_date=lesson_date or date(2026, 6, 10),
        duration=1.0,
        status='confirmed',
    )


def _make_draft_invoice(student, school, amount=Decimal('120.00')):
    """Create a draft PreBillingInvoice for testing send/void endpoints."""
    return PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='draft',
        amount=amount,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )


# ---------------------------------------------------------------------------
# Helcim HTTP mock helpers
# ---------------------------------------------------------------------------

def _helcim_create_invoice_ok():
    """Mock for successful Helcim create_invoice call."""
    return Mock(
        ok=True,
        status_code=200,
        json=lambda: {'invoiceId': 'inv_test_123', 'token': 'tok_test_abc', 'invoiceNumber': '001'},
        text='',
    )


def _helcim_create_customer_ok():
    """Mock for successful Helcim create_customer call."""
    return Mock(
        ok=True,
        status_code=200,
        json=lambda: {'id': 99001},
        text='',
    )


def _helcim_cancel_invoice_ok():
    """Mock for successful Helcim cancel_invoice call."""
    return Mock(
        ok=True,
        status_code=200,
        json=lambda: {},
        text='',
    )


def _helcim_cancel_invoice_fail():
    """Mock for failed Helcim cancel_invoice (settled invoice)."""
    return Mock(
        ok=False,
        status_code=400,
        text='settled invoice',
        json=lambda: {'error': 'settled invoice'},
    )


# ---------------------------------------------------------------------------
# Tests — generate drafts (BILL-03)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_generate_drafts(management_client, school, teacher_user, student_with_contact):
    """
    POST generate endpoint returns 200 with generated/skipped_existing/skipped_no_contact.
    BILL-03: draft generation creates PreBillingInvoice per student with BillableContact.
    """
    # Target the CURRENT month explicitly so the confirmed-Lesson sourcing path is
    # exercised. Generate now defaults to NEXT month (Phase 24 D-03/D-07), which would
    # source from RecurringLessonsSchedule instead.
    today = date.today()
    student, contact = student_with_contact
    _make_confirmed_lesson(
        student, teacher_user, school, lesson_date=date(today.year, today.month, 10)
    )

    # Student without contact — must be skipped
    User.objects.create_user(
        email="no_contact@prebilling.test",
        password="pass",
        user_type="student",
        first_name="No",
        last_name="Contact",
        school=school,
        is_approved=True,
    )

    url = reverse('management_pre_billing_generate')
    response = management_client.post(
        url, {'month': today.month, 'year': today.year}, format='json'
    )

    assert response.status_code == 200
    assert response.data['generated'] >= 1
    assert response.data['skipped_no_contact'] >= 1
    assert 'skipped_existing' in response.data
    assert 'skipped_no_schedule' in response.data  # Phase 24 D-09
    assert PreBillingInvoice.objects.filter(school=school).count() >= 1


@pytest.mark.django_db
def test_generate_drafts_incremental(management_client, school, teacher_user, student_with_contact):
    """
    POST generate is idempotent and incremental — students with an existing invoice
    for the current period are skipped; new students get a fresh draft.
    BILL-03: no duplicate drafts; skipped_existing count reflects pre-existing invoices.
    """
    student, contact = student_with_contact

    today = date.today()
    period_start = today.replace(day=1)
    import calendar
    last_day = calendar.monthrange(today.year, today.month)[1]
    period_end = today.replace(day=last_day)

    # Pre-create a draft for the existing student
    PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='draft',
        amount=Decimal('120.00'),
        period_start=period_start,
        period_end=period_end,
    )

    # Target the SAME period the pre-created draft lives in (current month). Generate
    # now defaults to next month (Phase 24 D-03/D-07), so the period must be explicit.
    url = reverse('management_pre_billing_generate')
    response = management_client.post(
        url, {'month': today.month, 'year': today.year}, format='json'
    )

    assert response.status_code == 200
    # Phase 24 D-10: a pre-existing DRAFT in the targeted period is refreshed, not
    # skipped — so it is NOT counted in skipped_existing (only sent/adjusted are).
    # The student must still have exactly one invoice (no duplicate created).
    assert PreBillingInvoice.objects.filter(school=school, student=student).count() == 1


@pytest.mark.django_db
def test_duplicate_prebilling_invoice_blocked_by_constraint(school, student_with_contact):
    """
    Bug 8 / duplicate protection: the DB constraint
    unique_prebilling_per_student_period prevents two invoices for the same
    student+school+period, even if a concurrent generate slips past the app-level
    existence check.
    """
    from django.db import IntegrityError, transaction
    student, _ = student_with_contact
    period_start = date(2026, 1, 1)
    period_end = date(2026, 1, 31)

    PreBillingInvoice.objects.create(
        student=student, school=school, status='draft', amount=Decimal('100.00'),
        period_start=period_start, period_end=period_end,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PreBillingInvoice.objects.create(
                student=student, school=school, status='draft', amount=Decimal('100.00'),
                period_start=period_start, period_end=period_end,
            )


# ---------------------------------------------------------------------------
# Tests — send invoice (BILL-05, BILL-07)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_invoice(management_client, school, teacher_user, student_with_contact):
    """
    POST send endpoint creates Helcim customer (lazy), creates invoice, transitions to sent.
    BILL-05: contact.helcim_customer_id stored; BILL-07: helcim_invoice_id + payment_token saved.
    """
    student, contact = student_with_contact
    invoice = _make_draft_invoice(student, school)
    lesson = _make_confirmed_lesson(student, teacher_user, school)
    invoice.lessons.add(lesson)

    with patch('billing.services.helcim_client.requests.post') as mock_post, \
         patch('billing.services.email_service.PreBillingEmailService.send_payment_request') as mock_email:
        # First call: create_customer; second call: create_invoice
        mock_post.side_effect = [_helcim_create_customer_ok(), _helcim_create_invoice_ok()]
        mock_email.return_value = (True, 'sent')

        url = reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        response = management_client.post(url, format='json')

    assert response.status_code == 200

    contact.refresh_from_db()
    invoice.refresh_from_db()
    assert contact.helcim_customer_id == str(99001)
    assert invoice.status == 'sent'
    assert invoice.helcim_invoice_id == 'inv_test_123'
    assert invoice.payment_token == 'tok_test_abc'


@pytest.mark.django_db
def test_send_sets_status(management_client, school, teacher_user, student_with_contact):
    """
    POST send transitions invoice status from draft to sent.
    BILL-07: status field must be 'sent' after successful send.
    """
    student, contact = student_with_contact
    # Pre-set customer ID so the customer creation mock isn't needed
    contact.helcim_customer_id = 'cust_existing_99'
    contact.save()

    invoice = _make_draft_invoice(student, school)
    lesson = _make_confirmed_lesson(student, teacher_user, school)
    invoice.lessons.add(lesson)

    with patch('billing.services.helcim_client.requests.post') as mock_post, \
         patch('billing.services.email_service.PreBillingEmailService.send_payment_request') as mock_email:
        mock_post.return_value = _helcim_create_invoice_ok()
        mock_email.return_value = (True, 'sent')

        url = reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        response = management_client.post(url, format='json')

    invoice.refresh_from_db()
    assert invoice.status == 'sent'


# ---------------------------------------------------------------------------
# Tests — send all (BILL-05 bulk)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_all_enqueues_run_instead_of_sending(management_client, school, teacher_user, student_with_contact):
    """
    Batch-queue wave: POST send-all snapshots the period's drafts into an
    InvoiceSendRun (202) and performs NO Helcim/email work in the request —
    the worker owns the sending. BILL-07 semantics move to the run lifecycle.
    """
    from billing.models import InvoiceSendRun

    student, contact = student_with_contact
    june = _make_draft_invoice(student, school)  # period_start 2026-06-01
    lesson = _make_confirmed_lesson(student, teacher_user, school)
    june.lessons.add(lesson)

    with patch('billing.services.helcim_client.requests.post') as helcim_post:
        url = reverse('management_pre_billing_send_all')
        response = management_client.post(url, {'month': 6, 'year': 2026}, format='json')

    assert response.status_code == 202
    helcim_post.assert_not_called()  # request does zero provider work
    run = InvoiceSendRun.objects.get(pk=response.data['id'])
    assert run.status == 'queued'
    assert run.item_count == 1
    assert list(run.items.values_list('invoice_id', flat=True)) == [june.id]
    june.refresh_from_db()
    assert june.status == 'draft'  # untouched until the worker claims it


@pytest.mark.django_db
def test_send_all_scoped_to_period(management_client, school, teacher_user, student_with_contact):
    """
    Regression (2026-08-27, re-expressed for send runs): the run snapshot
    contains ONLY the requested period's drafts — other months untouched.
    """
    from billing.models import InvoiceSendRun

    student, contact = student_with_contact
    june = _make_draft_invoice(student, school)
    july = PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='draft',
        amount=Decimal('120.00'),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )

    url = reverse('management_pre_billing_send_all')
    response = management_client.post(url, {'month': 6, 'year': 2026}, format='json')

    assert response.status_code == 202
    run = InvoiceSendRun.objects.get(pk=response.data['id'])
    assert list(run.items.values_list('invoice_id', flat=True)) == [june.id]
    assert july.send_items.count() == 0


# ---------------------------------------------------------------------------
# Tests — remove lesson / void + recreate (BILL-08, BILL-09)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_remove_lesson(management_client, school, teacher_user, student_with_contact):
    """
    POST remove-lesson voids old Helcim invoice, creates new one, transitions to adjusted.
    BILL-08: invoice.status == 'adjusted'; lessons.count reduced; helcim_invoice_id updated.
    """
    student, contact = student_with_contact
    contact.helcim_customer_id = 'cust_existing_88'
    contact.save()

    invoice = PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='sent',
        amount=Decimal('180.00'),
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        helcim_invoice_id='inv_old_456',
        payment_token='tok_old_xyz',
    )
    lesson_dates = [date(2026, 6, 3), date(2026, 6, 10), date(2026, 6, 17)]
    lessons_created = []
    for d in lesson_dates:
        lesson = _make_confirmed_lesson(student, teacher_user, school, lesson_date=d)
        invoice.lessons.add(lesson)
        lessons_created.append(lesson)

    lesson_to_remove = lessons_created[0]

    new_invoice_response = Mock(
        ok=True,
        status_code=200,
        json=lambda: {'invoiceId': 'inv_new_789', 'token': 'tok_new_xyz', 'invoiceNumber': '002'},
        text='',
    )

    with patch('billing.services.helcim_client.requests.put') as mock_put, \
         patch('billing.services.helcim_client.requests.post') as mock_post, \
         patch('billing.services.email_service.PreBillingEmailService.send_payment_request') as mock_email:
        mock_put.return_value = _helcim_cancel_invoice_ok()
        mock_post.return_value = new_invoice_response
        mock_email.return_value = (True, 'sent')

        url = reverse('management_pre_billing_remove_lesson', kwargs={'invoice_id': invoice.id})
        response = management_client.post(url, data={'lesson_id': lesson_to_remove.id}, format='json')

    assert response.status_code == 200

    invoice.refresh_from_db()
    assert invoice.status == 'adjusted'
    assert invoice.lessons.count() == 2
    assert invoice.helcim_invoice_id == 'inv_new_789'


@pytest.mark.django_db
def test_void_failure_inline_error(management_client, school, teacher_user, student_with_contact):
    """
    POST remove-lesson returns 400 with 'Cannot void' error when cancel fails.
    BILL-09: void failure must return inline error, invoice status unchanged.
    """
    student, contact = student_with_contact
    contact.helcim_customer_id = 'cust_existing_77'
    contact.save()

    invoice = PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='sent',
        amount=Decimal('120.00'),
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        helcim_invoice_id='inv_settled_321',
        payment_token='tok_settled_abc',
    )
    lesson = _make_confirmed_lesson(student, teacher_user, school)
    invoice.lessons.add(lesson)

    with patch('billing.services.helcim_client.requests.put') as mock_put:
        mock_put.return_value = _helcim_cancel_invoice_fail()

        url = reverse('management_pre_billing_remove_lesson', kwargs={'invoice_id': invoice.id})
        response = management_client.post(url, data={'lesson_id': lesson.id}, format='json')

    assert response.status_code == 400
    assert 'Cannot void' in response.data['error']

    invoice.refresh_from_db()
    assert invoice.status == 'sent'  # unchanged


# ---------------------------------------------------------------------------
# Tests — B-1: end-to-end wallet-timing no-double-bill (BILL-04)
#
# The bill-ahead flow and end-of-month batch approval flow are NOT linked
# invoice-to-invoice. They meet only at the period-keyed StudentCreditAccount
# wallet (F-3): parent pays → wallet +; batch approval drains → wallet −.
# These tests are the guardrail that the two flows do not double-charge during
# the current-month / next-month transition, including a student who carries a
# rollover credit into the cycle.
# ---------------------------------------------------------------------------

# Future period: NEXT calendar month relative to today, so generate exercises
# the 24-01 RecurringLessonsSchedule-sourcing branch (D-04/D-08) rather than the
# confirmed-Lesson path.
def _next_period():
    today = date.today()
    if today.month == 12:
        return today.year + 1, 1
    return today.year, today.month + 1


def _make_active_schedule(student, teacher, school, year, month,
                          student_rate=Decimal('60.00'),
                          teacher_rate=Decimal('45.00'),
                          duration=Decimal('1.0'),
                          day_of_week=2):
    """
    Active weekly recurring schedule starting on the 1st of the target month.

    start_date is set to the first of the billing month so every weekly
    occurrence within the month is projected by generate_lessons_for_month.
    """
    return RecurringLessonsSchedule.objects.create(
        teacher=teacher,
        student=student,
        school=school,
        day_of_week=day_of_week,
        start_time=time(15, 0),
        duration=duration,
        lesson_type='online',
        teacher_rate=teacher_rate,
        student_rate=student_rate,
        is_active=True,
        start_date=date(year, month, 1),
    )


def _generate_for_period(client, year, month):
    url = reverse('management_pre_billing_generate')
    return client.post(url, {'month': month, 'year': year}, format='json')


def _pay_invoice_into_wallet(student, school, amount):
    """
    Simulate the parent paying the bill-ahead invoice: credit the period-keyed
    wallet by the paid amount and write the immutable ledger entry
    (CreditTransaction type='pre_billing_payment' → balance += amount).
    This mirrors the payment path the rest of the suite uses; no real Helcim
    HTTP is involved.
    """
    account, _ = StudentCreditAccount.objects.get_or_create(
        student=student, school=school, defaults={'balance': Decimal('0.00')},
    )
    account.balance += amount
    account.save(update_fields=['balance'])
    CreditTransaction.objects.create(
        account=account, school=school,
        type='pre_billing_payment', amount=amount,
    )
    return account


def _make_submitted_batch_for_period(teacher, school, student, year, month,
                                     count, student_rate=Decimal('60.00'),
                                     teacher_rate=Decimal('45.00'),
                                     duration=Decimal('1.0')):
    """
    Build a teacher MonthlyInvoiceBatch for the SAME year/month with ``count``
    completed BatchLessonItems for ``student`` and mark it submitted (ready to
    approve). Mirrors the batch-create + approve pattern in test_batch_credit.py.
    """
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher, school=school, month=month, year=year,
    )
    for i in range(count):
        item = BatchLessonItem.objects.create(
            batch=batch,
            student=student,
            scheduled_date=date(year, month, 1 + i),
            start_time=time(15, 0),
            duration=duration,
            lesson_type='online',
            teacher_rate=teacher_rate,
            student_rate=student_rate,
            status='completed',
        )
        # BatchLessonItem.save() auto-promotes the FIRST item for a student with
        # no prior Lesson/BatchLessonItem to status='trial' (zero-charge). These
        # are delivered, billable lessons, so force status back to 'completed' via
        # an update that bypasses the adding-time auto-trial branch.
        if item.status != 'completed':
            BatchLessonItem.objects.filter(pk=item.pk).update(status='completed')
    batch.status = 'submitted'
    batch.save()
    return batch


def _approve_batch(management_client, batch):
    url = reverse('management_approve_batch', kwargs={'batch_id': batch.id})
    return management_client.post(url)


@pytest.mark.django_db
def test_bill_ahead_pay_then_approve_no_double_charge(
    management_client, school, school_settings, teacher_user, student_with_contact,
):
    """
    B-1 end-to-end: bill-ahead (next month) → parent pays (wallet +) → that
    same month's teacher batch approved later (wallet −) nets to the correct
    balance with NO double charge.

    Cycle:
      1. Active recurring schedule for NEXT month → generate sources from it
         (D-04/D-08); draft amount = student_rate × projected occurrences.
      2. Parent pays → wallet += draft amount (CreditTransaction='pre_billing_payment').
      3. That month's batch (same lessons delivered) approved → wallet drained
         by student_rate per completed item (management.py:1693-1696).
      4. Final wallet balance = paid-in − lessons-consumed == 0 (no double charge).

    The genuine reconciliation at management.py:1710-1737 runs unmodified (D-06).
    """
    student, contact = student_with_contact
    year, month = _next_period()
    student_rate = Decimal('60.00')

    # Wallet starts empty (no rollover for this scenario).
    StudentCreditAccount.objects.create(
        student=student, school=school, balance=Decimal('0.00'),
    )

    schedule = _make_active_schedule(
        student, teacher_user, school, year, month, student_rate=student_rate,
    )
    # Projected occurrences for the period drive both the draft amount AND the
    # number of delivered lessons in the batch, so the two flows are matched.
    projected = schedule.generate_lessons_for_month(year, month)
    n = len(projected)
    assert n > 0, "schedule must project at least one lesson into the billing month"

    gross = student_rate * Decimal(n)

    # Step 1: generate the bill-ahead draft from the recurring schedule.
    response = _generate_for_period(management_client, year, month)
    assert response.status_code == 200
    assert response.data['generated'] >= 1

    invoice = PreBillingInvoice.objects.get(
        student=student, school=school, period_start=date(year, month, 1),
    )
    # No rollover → draft amount equals the projected gross.
    assert invoice.amount == gross
    # Future-period invoices carry no Lesson rows (intentional, 24-01).
    assert invoice.lessons.count() == 0

    # Step 2: parent pays the invoice → wallet funded.
    _pay_invoice_into_wallet(student, school, invoice.amount)
    account = StudentCreditAccount.objects.get(student=student, school=school)
    assert account.balance == gross  # paid-in

    # Step 3: later, that month's batch (same n lessons delivered) is approved.
    batch = _make_submitted_batch_for_period(
        teacher_user, school, student, year, month, count=n,
        student_rate=student_rate,
    )
    approve_resp = _approve_batch(management_client, batch)
    assert approve_resp.status_code == 200

    # Step 4: wallet drained by lessons-consumed; nets to zero — NO double charge.
    account.refresh_from_db()
    expected_final = max(Decimal('0.00'), gross - (student_rate * Decimal(n)))
    assert account.balance == expected_final == Decimal('0.00')

    # No duplicate PreBillingInvoice for the same (student, school, period_start).
    assert PreBillingInvoice.objects.filter(
        student=student, school=school, period_start=date(year, month, 1),
    ).count() == 1

    # Reconciliation populated the period-keyed credit fields (D-06 path ran).
    from billing.models import StudentInvoice
    student_invoice = StudentInvoice.objects.get(batch=batch, student=student)
    # gross delivered == pre-billing amount → no extra credit applied, charge = pre-billing.
    assert student_invoice.amount_after_credit == invoice.amount


@pytest.mark.django_db
def test_bill_ahead_with_rollover_credit_nets_correctly(
    management_client, school, school_settings, teacher_user, student_with_contact,
):
    """
    B-1 rollover variant: a student who STARTS the cycle carrying a non-zero
    rollover credit. Bill-ahead nets the rollover (amount = gross − rollover);
    the parent pays the reduced amount; the batch approval drains the full gross;
    the final wallet balance is the rollover-adjusted expected value (zero) with
    NO double charge.

    Arithmetic:
      gross         = student_rate × n
      draft amount  = gross − rollover        (credit netted at generation)
      after pay-in  = rollover + (gross − rollover) = gross
      after drain   = gross − (student_rate × n) = 0
    """
    student, contact = student_with_contact
    year, month = _next_period()
    student_rate = Decimal('60.00')
    rollover = Decimal('30.00')

    # Wallet starts with a rollover credit carried into the cycle.
    StudentCreditAccount.objects.create(
        student=student, school=school, balance=rollover,
    )

    schedule = _make_active_schedule(
        student, teacher_user, school, year, month, student_rate=student_rate,
    )
    projected = schedule.generate_lessons_for_month(year, month)
    n = len(projected)
    assert n > 0
    gross = student_rate * Decimal(n)
    assert gross > rollover, "test assumes gross exceeds the rollover credit"

    # Step 1: generate — credit is netted at draft creation (amount = gross − rollover).
    response = _generate_for_period(management_client, year, month)
    assert response.status_code == 200

    invoice = PreBillingInvoice.objects.get(
        student=student, school=school, period_start=date(year, month, 1),
    )
    expected_draft = gross - rollover
    assert invoice.amount == expected_draft

    # Step 2: parent pays the reduced (rollover-adjusted) amount.
    _pay_invoice_into_wallet(student, school, invoice.amount)
    account = StudentCreditAccount.objects.get(student=student, school=school)
    # rollover + (gross − rollover) == gross funded in the wallet.
    assert account.balance == gross

    # Step 3: approve the month's batch (n delivered lessons) → drain full gross.
    batch = _make_submitted_batch_for_period(
        teacher_user, school, student, year, month, count=n,
        student_rate=student_rate,
    )
    approve_resp = _approve_batch(management_client, batch)
    assert approve_resp.status_code == 200

    # Step 4: rollover-adjusted final balance nets to zero — no double charge.
    account.refresh_from_db()
    expected_final = max(Decimal('0.00'), gross - (student_rate * Decimal(n)))
    assert account.balance == expected_final == Decimal('0.00')

    # The pay-in ledger entry recorded the reduced amount, proving the rollover
    # reduced what the parent was charged (not an extra deduction).
    paid_txn = CreditTransaction.objects.get(
        account=account, type='pre_billing_payment',
    )
    assert paid_txn.amount == expected_draft

    assert PreBillingInvoice.objects.filter(
        student=student, school=school, period_start=date(year, month, 1),
    ).count() == 1
