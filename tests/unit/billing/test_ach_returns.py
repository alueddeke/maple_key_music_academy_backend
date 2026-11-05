"""
Unit tests for returned bank (ACH/EFT) payments (MAP-232).

A bank payment can come back days later as returned (NSF, closed account).
Helcim cannot simulate a return on a test account and sends no bank webhooks;
the only signal is statusClearing on GET /v2/ach/transactions. sync_helcim_ach
runs a returns pass every tick: a returned payment takes back what it
credited, as far as the balance allows, re-opens the invoice, flags the
account, alerts (event 'returned') and notifies management in the bell.

Helcim is mocked at the client boundary (`list_ach_transactions`); the
command, the credit path, the return handler and the ledger run for real.
Rows come from test_sync_helcim_ach.ach_row (the one documented sample) with
statusClearing read from the command's table.

Owner rulings 2026-11-05 (MAP-232 comment): ledger type 'reversal'; in-app
notification, no email; RETURNED only, CONTESTED dropped (Helcim 2026-10-13);
unknown statusClearing → needs_attention; a returned row the app never saw
is recorded 'returned'; a credited event whose invoice is gone →
needs_attention, no money moved.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models import Sum
from django.utils import timezone
from prometheus_client import REGISTRY

from billing.management.commands import sync_helcim_ach as command_module
from billing.models import (
    CreditTransaction,
    HelcimWebhookEvent,
    PreBillingInvoice,
    StudentCreditAccount,
)
from billing.services import ledger
from billing.services.helcim_client import HelcimAPIError
from billing.services.webhook_processing import ALERT_STATES, apply_bank_return
from notifications.models import Notification
from tests.unit.billing.test_sync_helcim_ach import ach_row

ACH_LIST = 'billing.services.helcim_client.HelcimClient.list_ach_transactions'
CARD_GET = 'billing.services.webhook_processing.HelcimClient.get_card_transaction'
CARD_LIST = 'billing.services.helcim_client.HelcimClient.list_card_transactions'
NOTIFY = 'billing.services.webhook_processing.notify_bank_payment_returned'

PRICE = Decimal('60.00')
ZERO = Decimal('0.00')
User = get_user_model()


# --- helpers ------------------------------------------------------------------------

def _clearing(name):
    """Helcim's statusClearing value for a canonical name, read from the command's table."""
    return next(value for value, known in command_module.STATUS_CLEARING_NAMES.items() if known == name)


def _row(tx_id, invoice_number, amount=PRICE, status='APPROVED', clearing='OPENED', **overrides):
    overrides.setdefault(command_module.ROW_STATUS_CLEARING_KEY, _clearing(clearing))
    return ach_row(tx_id, invoice_number, str(amount), status=status, **overrides)


def _sync(payments=(), returns=(), *args):
    """
    Run the command with Helcim answering `payments` on the payments pass and
    `returns` on the returns pass (the call that filters on statusClearing).
    Returns (client mock, output).
    """
    def answer(**kwargs):
        if 'status_clearing' in kwargs:
            return list(returns) if kwargs.get('page', 1) == 1 else []
        return list(payments) if kwargs.get('page', 1) == 1 else []

    out = StringIO()
    with mock.patch(ACH_LIST, side_effect=answer) as listed:
        call_command('sync_helcim_ach', *args, stdout=out, stderr=out)
    return listed, out.getvalue()


def _returns_calls(listed):
    return [call for call in listed.call_args_list if 'status_clearing' in call.kwargs]


def _invoice(school, student, number, amount=PRICE, period=(date(2026, 10, 1), date(2026, 10, 31)), **fields):
    return PreBillingInvoice.objects.create(
        student=student, school=school, status='sent', amount=amount,
        period_start=period[0], period_end=period[1],
        helcim_invoice_number=number, **fields,
    )


def _credited_bank_payment(school, student, tx_id, number, amount=PRICE, **invoice_fields):
    """An invoice paid by bank through the real MAP-217 path. Returns (invoice, account, event)."""
    invoice = _invoice(school, student, number, amount=amount, **invoice_fields)
    _sync(payments=[_row(tx_id, number, amount)])
    event = HelcimWebhookEvent.objects.get(rail='ach', helcim_transaction_id=str(tx_id))
    assert event.processing_status == 'credited'
    invoice.refresh_from_db()
    assert invoice.status == 'paid' and invoice.paid_via == 'bank'
    account = StudentCreditAccount.objects.get(student=student, school=school)
    return invoice, account, event


def _spend(account, amount, school, teacher, student):
    """Use up wallet credit through the ledger (stands in for a batch approval)."""
    lesson_invoice = _invoice(school, student, f'SPEND-{amount}', amount=amount,
                              period=(date(2026, 11, 1), date(2026, 11, 30)))
    with transaction.atomic():
        ledger.post(account, type='lesson_charge', amount=amount, source_invoice=lesson_invoice)


def _assert_invariant(account):
    """balance == Σ(amount × balance effect of its type) over the account's ledger rows."""
    account.refresh_from_db()
    expected = sum(
        (row.amount * ledger.BALANCE_EFFECT[row.type]
         for row in CreditTransaction.objects.filter(account=account, legacy=False)),
        ZERO,
    )
    assert account.balance == expected
    assert account.balance >= ZERO


def _rows(account, type):
    return CreditTransaction.objects.filter(account=account, type=type)


def _total(account, type):
    return _rows(account, type).aggregate(total=Sum('amount'))['total'] or ZERO


# --- Change 2: a credited payment is returned ----------------------------------------

@pytest.mark.django_db
def test_return_after_credit_reverses_the_credit_and_reopens_the_invoice(
        school, student_user, django_capture_on_commit_callbacks):
    invoice, account, event = _credited_bank_payment(school, student_user, 7001, 'MK-r1')
    credited = _total(account, 'pre_billing_payment')

    with django_capture_on_commit_callbacks(execute=True):
        _sync(returns=[_row(7001, 'MK-r1', clearing='RETURNED')])

    event.refresh_from_db()
    invoice.refresh_from_db()
    account.refresh_from_db()
    reversal = _rows(account, 'reversal').get()
    assert reversal.amount == credited
    assert reversal.source_event_id == event.pk
    assert account.balance == ZERO
    assert not _rows(account, 'shortfall').exists()
    assert account.needs_attention is True
    assert invoice.status == 'sent'
    assert invoice.paid_via == ''
    assert event.processing_status == 'returned'
    assert event.processing_status in ALERT_STATES
    assert event.last_error
    _assert_invariant(account)


@pytest.mark.django_db
def test_return_on_an_adjusted_invoice_reopens_it_as_adjusted(school, student_user):
    invoice, account, _ = _credited_bank_payment(school, student_user, 7002, 'MK-r2', revision=1)

    _sync(returns=[_row(7002, 'MK-r2', clearing='RETURNED')])

    invoice.refresh_from_db()
    assert invoice.status == 'adjusted'
    assert invoice.paid_via == ''
    _assert_invariant(account)


@pytest.mark.django_db
def test_return_above_the_balance_reverses_to_zero_and_records_the_rest_as_shortfall(
        school, teacher_user, student_user):
    invoice, account, event = _credited_bank_payment(school, student_user, 7003, 'MK-r3')
    credited = _total(account, 'pre_billing_payment')
    spent = (credited / 3).quantize(Decimal('0.01'))
    _spend(account, spent, school, teacher_user, student_user)
    account.refresh_from_db()
    balance_before = account.balance

    _sync(returns=[_row(7003, 'MK-r3', clearing='RETURNED')])

    account.refresh_from_db()
    reversal = _rows(account, 'reversal').get()
    shortfall = _rows(account, 'shortfall').get()
    assert reversal.amount == balance_before
    assert shortfall.amount == credited - balance_before
    assert shortfall.source_invoice_id == invoice.pk
    assert shortfall.source_event_id is None
    assert account.balance == ZERO
    assert account.needs_attention is True
    _assert_invariant(account)


@pytest.mark.django_db
def test_return_on_an_empty_wallet_records_only_a_shortfall(school, teacher_user, student_user):
    invoice, account, event = _credited_bank_payment(school, student_user, 7004, 'MK-r4')
    credited = _total(account, 'pre_billing_payment')
    _spend(account, credited, school, teacher_user, student_user)

    _sync(returns=[_row(7004, 'MK-r4', clearing='RETURNED')])

    event.refresh_from_db()
    account.refresh_from_db()
    assert not _rows(account, 'reversal').exists()
    assert _rows(account, 'shortfall').get().amount == credited
    assert account.balance == ZERO
    assert event.processing_status == 'returned'
    _assert_invariant(account)


@pytest.mark.django_db
def test_second_tick_posts_nothing(school, student_user, django_capture_on_commit_callbacks):
    _, account, event = _credited_bank_payment(school, student_user, 7005, 'MK-r5')
    returned = [_row(7005, 'MK-r5', clearing='RETURNED')]
    with django_capture_on_commit_callbacks(execute=True):
        _sync(returns=returned)
    rows_after_first = CreditTransaction.objects.filter(account=account).count()
    notifications_after_first = Notification.objects.count()
    event.refresh_from_db()
    stamped = event.processed_at

    with django_capture_on_commit_callbacks(execute=True):
        _sync(returns=returned)

    event.refresh_from_db()
    assert CreditTransaction.objects.filter(account=account).count() == rows_after_first
    assert Notification.objects.count() == notifications_after_first
    assert event.processing_status == 'returned'
    assert event.processed_at == stamped
    _assert_invariant(account)


def _in_thread(fn, barrier):
    """Run fn on its own DB connection after every worker reached the barrier."""
    def _go():
        connection.close()
        barrier.wait(timeout=10)
        try:
            return fn()
        finally:
            connection.close()
    return _go


@pytest.mark.django_db(transaction=True)
def test_concurrent_returns_reverse_exactly_once(school, student_user):
    """Two callers holding stale copies of the same credited event (Postgres row locks)."""
    _, account, event = _credited_bank_payment(school, student_user, 7006, 'MK-r6')
    credited = _total(account, 'pre_billing_payment')
    barrier = threading.Barrier(2)

    def _return():
        stale = HelcimWebhookEvent.objects.get(pk=event.pk)
        return apply_bank_return(stale).processing_status

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_in_thread(_return, barrier)) for _ in range(2)]
        outcomes = [f.result(timeout=20) for f in futures]

    assert outcomes == ['returned', 'returned']
    assert _rows(account, 'reversal').count() == 1
    assert _total(account, 'reversal') == credited
    _assert_invariant(account)


# --- Change 3: a payment that never credited is returned -----------------------------

@pytest.mark.django_db
def test_return_before_any_credit_records_returned_without_a_ledger_row(school, student_user):
    invoice = _invoice(school, student_user, 'MK-r7')
    _sync(payments=[_row(7007, 'MK-r7', status='PENDING')])
    event = HelcimWebhookEvent.objects.get(rail='ach', helcim_transaction_id='7007')
    assert event.processing_status == 'awaiting_bank'

    _sync(payments=[_row(7007, 'MK-r7', status='PENDING')],
          returns=[_row(7007, 'MK-r7', status='PENDING', clearing='RETURNED')])

    event.refresh_from_db()
    invoice.refresh_from_db()
    assert event.processing_status == 'returned'
    assert not CreditTransaction.objects.exists()
    assert invoice.status == 'sent'


@pytest.mark.django_db
def test_a_returned_row_the_app_never_saw_is_recorded_returned(
        school, student_user, management_user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        _, out = _sync(returns=[_row(7008, 'MK-unknown', clearing='RETURNED')])

    event = HelcimWebhookEvent.objects.get(rail='ach', helcim_transaction_id='7008')
    assert event.processing_status == 'returned'
    assert event.school_id == school.pk
    assert not CreditTransaction.objects.exists()
    notification = Notification.objects.get(user=management_user)
    assert notification.type == 'bank_payment_returned'
    assert notification.link_url == ''
    assert 'first seen on the returns pass' in out


# --- the returns pass ------------------------------------------------------------------

@pytest.mark.django_db
def test_returns_pass_lists_returned_from_the_lookback_window(school):
    earliest = (timezone.now() - timedelta(days=command_module.RETURN_LOOKBACK_DAYS)).date()

    listed, _ = _sync()

    latest = (timezone.now() - timedelta(days=command_module.RETURN_LOOKBACK_DAYS)).date()
    calls = _returns_calls(listed)
    assert len(calls) == 1
    assert calls[0].kwargs['status_clearing'] == command_module.RETURNED_CLEARING
    assert calls[0].kwargs['date_from'] in {earliest, latest}


@pytest.mark.django_db
def test_opened_and_cleared_rows_are_not_returns(school, student_user):
    """Only seen if Helcim ignores the statusClearing filter."""
    invoice, account, event = _credited_bank_payment(school, student_user, 7009, 'MK-r9')

    _sync(returns=[_row(7009, 'MK-r9', clearing='OPENED'),
                   _row(7010, 'MK-r10', clearing='CLEARED')])

    event.refresh_from_db()
    invoice.refresh_from_db()
    assert event.processing_status == 'credited'
    assert invoice.status == 'paid'
    assert not _rows(account, 'reversal').exists()
    assert not HelcimWebhookEvent.objects.filter(helcim_transaction_id='7010').exists()


@pytest.mark.django_db
def test_an_unknown_clearing_value_lands_in_needs_attention_and_moves_no_money(school, student_user):
    invoice, account, event = _credited_bank_payment(school, student_user, 7011, 'MK-r11')
    unknown = max(command_module.STATUS_CLEARING_NAMES) + 90
    balance_before = account.balance

    _sync(returns=[_row(7011, 'MK-r11', **{command_module.ROW_STATUS_CLEARING_KEY: unknown})])

    event.refresh_from_db()
    account.refresh_from_db()
    invoice.refresh_from_db()
    assert event.processing_status == 'needs_attention'
    assert event.processing_status in ALERT_STATES
    assert str(unknown) in event.last_error
    assert account.balance == balance_before
    assert not _rows(account, 'reversal').exists()
    assert invoice.status == 'paid'
    _assert_invariant(account)


@pytest.mark.django_db
def test_a_return_after_an_unknown_clearing_value_still_reverses_the_credit(school, student_user):
    """needs_attention is not 'never credited': the ledger says what to take back."""
    _, account, event = _credited_bank_payment(school, student_user, 7012, 'MK-r12')
    credited = _total(account, 'pre_billing_payment')
    _sync(returns=[_row(7012, 'MK-r12', **{command_module.ROW_STATUS_CLEARING_KEY: max(command_module.STATUS_CLEARING_NAMES) + 90})])

    _sync(returns=[_row(7012, 'MK-r12', clearing='RETURNED')])

    event.refresh_from_db()
    assert event.processing_status == 'returned'
    assert _total(account, 'reversal') == credited
    _assert_invariant(account)


@pytest.mark.django_db
def test_a_credited_return_whose_invoice_is_gone_moves_no_money(school, student_user):
    invoice, account, event = _credited_bank_payment(school, student_user, 7013, 'MK-r13')
    PreBillingInvoice.objects.filter(pk=invoice.pk).update(helcim_invoice_number='MK-r13-new')
    balance_before = account.balance

    _sync(returns=[_row(7013, 'MK-r13', clearing='RETURNED')])

    event.refresh_from_db()
    account.refresh_from_db()
    assert event.processing_status == 'needs_attention'
    assert account.balance == balance_before
    assert not _rows(account, 'reversal').exists()
    _assert_invariant(account)

    # The next tick leaves it flagged as it was (the 15-minute alert settles).
    stamped = event.processed_at
    _sync(returns=[_row(7013, 'MK-r13', clearing='RETURNED')])
    event.refresh_from_db()
    assert event.processing_status == 'needs_attention'
    assert event.processed_at == stamped


@pytest.mark.django_db
def test_a_helcim_error_on_the_returns_pass_changes_nothing(school, student_user):
    invoice, account, event = _credited_bank_payment(school, student_user, 7014, 'MK-r14')

    def answer(**kwargs):
        if 'status_clearing' in kwargs:
            raise HelcimAPIError('down', status_code=503)
        return []

    out = StringIO()
    with mock.patch(ACH_LIST, side_effect=answer):
        call_command('sync_helcim_ach', stdout=out, stderr=out)

    event.refresh_from_db()
    invoice.refresh_from_db()
    assert event.processing_status == 'credited'
    assert invoice.status == 'paid'
    assert 'returns pass' in out.getvalue()


@pytest.mark.django_db
def test_dry_run_lists_returns_and_changes_nothing(school, student_user):
    invoice, account, event = _credited_bank_payment(school, student_user, 7015, 'MK-r15')

    _, out = _sync((), [_row(7015, 'MK-r15', clearing='RETURNED'),
                        _row(7016, 'MK-r16', clearing='RETURNED')], '--dry-run')

    event.refresh_from_db()
    invoice.refresh_from_db()
    assert event.processing_status == 'credited'
    assert invoice.status == 'paid'
    assert not _rows(account, 'reversal').exists()
    assert not HelcimWebhookEvent.objects.filter(helcim_transaction_id='7016').exists()
    assert 'return ach=7015' in out


# --- Change 5: the alert ------------------------------------------------------------------

@pytest.mark.django_db
def test_the_failed_gauge_counts_a_returned_event(school, student_user):
    _credited_bank_payment(school, student_user, 7017, 'MK-r17')
    _sync(returns=[_row(7017, 'MK-r17', clearing='RETURNED')])

    with mock.patch(CARD_GET), mock.patch(CARD_LIST, return_value=[]), \
         mock.patch(ACH_LIST, return_value=[]):
        call_command('run_scheduler', '--once', stdout=StringIO())

    assert REGISTRY.get_sample_value('maplekey_webhook_events_failed_15m') == 1


# --- notification (owner ruling 2026-11-05: in-app, no email) ----------------------------

@pytest.mark.django_db
def test_a_return_notifies_every_active_management_user_of_the_school(
        school, second_school, student_user, management_user, django_capture_on_commit_callbacks):
    inactive = User.objects.create_user(
        email='gone@test.com', password='x', user_type='management',
        school=school, is_approved=True, is_active=False,
    )
    other_school = User.objects.create_user(
        email='other@test.com', password='x', user_type='management',
        school=second_school, is_approved=True,
    )
    _credited_bank_payment(school, student_user, 7018, 'MK-r18')

    with django_capture_on_commit_callbacks(execute=True):
        _sync(returns=[_row(7018, 'MK-r18', clearing='RETURNED')])

    notification = Notification.objects.get(user=management_user)
    assert notification.type == 'bank_payment_returned'
    assert notification.link_url == f'/management/students/{student_user.id}'
    assert student_user.get_full_name() in notification.message
    assert 'MK-r18' in notification.message
    assert not Notification.objects.filter(user__in=[inactive, other_school]).exists()


@pytest.mark.django_db
def test_a_failed_notification_does_not_undo_the_return(
        school, student_user, management_user, django_capture_on_commit_callbacks):
    _, account, event = _credited_bank_payment(school, student_user, 7019, 'MK-r19')
    credited = _total(account, 'pre_billing_payment')

    with mock.patch(NOTIFY, side_effect=RuntimeError('bell down')), \
         django_capture_on_commit_callbacks(execute=True):
        _sync(returns=[_row(7019, 'MK-r19', clearing='RETURNED')])

    event.refresh_from_db()
    assert event.processing_status == 'returned'
    assert _total(account, 'reversal') == credited
    assert not Notification.objects.exists()


# --- ledger constraints and the next payment ----------------------------------------------

@pytest.mark.django_db
def test_one_credit_and_one_reversal_per_event(school, student_user):
    _, account, event = _credited_bank_payment(school, student_user, 7020, 'MK-r20')
    _sync(returns=[_row(7020, 'MK-r20', clearing='RETURNED')])
    assert _rows(account, 'pre_billing_payment').filter(source_event=event).count() == 1
    assert _rows(account, 'reversal').filter(source_event=event).count() == 1

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CreditTransaction.objects.create(
                account=account, school=school, type='reversal',
                amount=Decimal('0.01'), source_event=event,
            )


@pytest.mark.django_db
def test_a_payment_after_the_return_credits_the_reopened_invoice(school, student_user):
    """Helcim puts the invoice back to DUE; the parent pays again through the same link."""
    invoice, account, _ = _credited_bank_payment(school, student_user, 7021, 'MK-r21')
    _sync(returns=[_row(7021, 'MK-r21', clearing='RETURNED')])

    _sync(payments=[_row(7022, 'MK-r21')])

    invoice.refresh_from_db()
    account.refresh_from_db()
    second = HelcimWebhookEvent.objects.get(rail='ach', helcim_transaction_id='7022')
    assert second.processing_status == 'credited'
    assert invoice.status == 'paid'
    assert invoice.paid_via == 'bank'
    assert account.balance == invoice.amount
    _assert_invariant(account)
