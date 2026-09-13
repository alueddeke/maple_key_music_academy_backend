"""
Unit tests for the sync_helcim_payments management command — pull-based
recovery for payments whose webhooks never arrived.
"""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone

from billing.models import (
    HelcimWebhookEvent,
    PreBillingInvoice,
    School,
    StudentCreditAccount,
    CreditTransaction,
    BillableContact,
)
from billing.services.helcim_client import HelcimAPIError

LIST_TARGET = 'billing.services.helcim_client.HelcimClient.list_card_transactions'
GET_TARGET = 'billing.services.webhook_processing.HelcimClient.get_card_transaction'


def _invoice_and_account(school, student_user, number, amount='60.00'):
    invoice = PreBillingInvoice.objects.create(
        student=student_user,
        school=school,
        status='sent',
        amount=Decimal(amount),
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        helcim_invoice_number=number,
    )
    account = StudentCreditAccount.objects.create(
        student=student_user, school=school, balance=Decimal('0.00')
    )
    return invoice, account


@pytest.mark.django_db
def test_sync_recovers_missed_payment(school, student_user):
    """Unseen APPROVED purchase → event created, credit applied, invoice paid."""
    invoice, account = _invoice_and_account(school, student_user, 'INV-SYNC-1')
    tx = {'transactionId': 90001, 'invoiceNumber': 'INV-SYNC-1', 'amount': 60,
          'status': 'APPROVED', 'type': 'purchase'}

    out = StringIO()
    with mock.patch(LIST_TARGET, return_value=[tx]), \
         mock.patch(GET_TARGET, return_value=tx):
        call_command('sync_helcim_payments', stdout=out)

    event = HelcimWebhookEvent.objects.get(helcim_transaction_id='90001')
    assert event.processing_status == 'credited'
    assert event.raw_payload.get('source') == 'sync'
    invoice.refresh_from_db()
    assert invoice.status == 'paid'
    account.refresh_from_db()
    assert account.balance == Decimal('60.00')
    assert 'credited' in out.getvalue()


@pytest.mark.django_db
def test_sync_is_idempotent(school, student_user):
    """Second run sees the recorded transaction and does nothing."""
    invoice, account = _invoice_and_account(school, student_user, 'INV-SYNC-2')
    tx = {'transactionId': 90002, 'invoiceNumber': 'INV-SYNC-2', 'amount': 60,
          'status': 'APPROVED', 'type': 'purchase'}

    with mock.patch(LIST_TARGET, return_value=[tx]), \
         mock.patch(GET_TARGET, return_value=tx):
        call_command('sync_helcim_payments', stdout=StringIO())
        call_command('sync_helcim_payments', stdout=StringIO())

    assert CreditTransaction.objects.count() == 1
    account.refresh_from_db()
    assert account.balance == Decimal('60.00')


@pytest.mark.django_db
def test_sync_never_credits_declines_or_refunds(school, student_user):
    """Gating applies on the pull path too."""
    invoice, account = _invoice_and_account(school, student_user, 'INV-SYNC-3')
    txs = [
        {'transactionId': 90003, 'invoiceNumber': 'INV-SYNC-3', 'amount': 60,
         'status': 'DECLINED', 'type': 'purchase'},
        {'transactionId': 90004, 'invoiceNumber': 'INV-SYNC-3', 'amount': 60,
         'status': 'APPROVED', 'type': 'refund'},
    ]

    def fake_get(self, tx_id):
        return next(t for t in txs if str(t['transactionId']) == str(tx_id))

    with mock.patch(LIST_TARGET, return_value=txs), \
         mock.patch(GET_TARGET, autospec=True, side_effect=fake_get):
        call_command('sync_helcim_payments', stdout=StringIO())

    assert CreditTransaction.objects.count() == 0
    account.refresh_from_db()
    assert account.balance == Decimal('0.00')
    assert HelcimWebhookEvent.objects.get(
        helcim_transaction_id='90003').processing_status == 'not_approved'
    assert HelcimWebhookEvent.objects.get(
        helcim_transaction_id='90004').processing_status == 'non_purchase'


@pytest.mark.django_db
def test_sync_dry_run_creates_nothing(school, student_user):
    tx = {'transactionId': 90005, 'invoiceNumber': 'X', 'amount': 60,
          'status': 'APPROVED', 'type': 'purchase'}
    out = StringIO()
    with mock.patch(LIST_TARGET, return_value=[tx]):
        call_command('sync_helcim_payments', '--dry-run', stdout=out)
    assert HelcimWebhookEvent.objects.count() == 0
    assert '1 new' in out.getvalue()


# ---------------------------------------------------------------------------
# MAP-154: per-school sync with a checkpoint window
# ---------------------------------------------------------------------------

def _tx(tx_id, number, created):
    return {'transactionId': tx_id, 'invoiceNumber': number, 'amount': 60,
            'status': 'APPROVED', 'type': 'purchase', 'dateCreated': created}


def _utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


def _list_by_token(rows_by_token):
    """
    autospec side_effect for HelcimClient.list_card_transactions: answers per
    client token, so each School's call is distinguishable.
    """
    def side_effect(self, **kwargs):
        return rows_by_token[self.api_token]
    return side_effect


@pytest.mark.django_db
def test_sync_iterates_every_school_with_checkpoint_window(school, second_school, student_user):
    """
    Every School row is synced with its own client. date_from is the
    checkpoint date (today − 30 days when null); rows before the checkpoint
    are dropped client-side (same-day overlap); the checkpoint advances to
    the newest dateCreated seen; a second run creates nothing.
    """
    invoice, account = _invoice_and_account(school, student_user, 'INV-SYNC-A')
    School.objects.filter(pk=second_school.pk).update(
        helcim_api_token='tok-second',
        helcim_last_synced_at=_utc(2026, 9, 1, 12, 0, 0),
    )
    # The fixture school has blank Helcim fields → its client carries the env token.
    from django.conf import settings
    rows = {
        # default school: null checkpoint → 30-day window, one row
        settings.HELCIM_API_TOKEN: [_tx(90101, 'INV-SYNC-A', '2026-09-05 10:00:00')],
        # second school: one row after the checkpoint, one before it (same day)
        'tok-second': [
            _tx(90102, 'NO-SUCH-INVOICE', '2026-09-02 09:00:00'),
            _tx(90103, 'NO-SUCH-INVOICE', '2026-09-01 08:00:00'),
        ],
    }
    all_rows = [r for group in rows.values() for r in group]

    def fake_get(self, tx_id):
        return next(t for t in all_rows if str(t['transactionId']) == str(tx_id))

    with mock.patch(LIST_TARGET, autospec=True, side_effect=_list_by_token(rows)) as mock_list, \
         mock.patch(GET_TARGET, autospec=True, side_effect=fake_get):
        call_command('sync_helcim_payments', stdout=StringIO())

    assert mock_list.call_count == 2
    calls = {c.args[0].api_token: c.kwargs for c in mock_list.call_args_list}
    default_kwargs = next(k for t, k in calls.items() if t != 'tok-second')
    assert default_kwargs['date_from'] == (timezone.now() - timedelta(days=30)).date()
    assert calls['tok-second']['date_from'] == date(2026, 9, 1)
    assert all(isinstance(k['limit'], int) and k['limit'] > 0 for k in calls.values())

    assert HelcimWebhookEvent.objects.get(helcim_transaction_id='90101').processing_status == 'credited'
    second_event = HelcimWebhookEvent.objects.get(helcim_transaction_id='90102')
    assert second_event.school == second_school
    assert not HelcimWebhookEvent.objects.filter(helcim_transaction_id='90103').exists()

    school.refresh_from_db()
    second_school.refresh_from_db()
    assert school.helcim_last_synced_at == _utc(2026, 9, 5, 10, 0, 0)
    assert second_school.helcim_last_synced_at == _utc(2026, 9, 2, 9, 0, 0)

    with mock.patch(LIST_TARGET, autospec=True, side_effect=_list_by_token(rows)), \
         mock.patch(GET_TARGET, autospec=True, side_effect=fake_get):
        call_command('sync_helcim_payments', stdout=StringIO())

    assert HelcimWebhookEvent.objects.count() == 2
    assert CreditTransaction.objects.count() == 1
    school.refresh_from_db()
    second_school.refresh_from_db()
    assert school.helcim_last_synced_at == _utc(2026, 9, 5, 10, 0, 0)
    assert second_school.helcim_last_synced_at == _utc(2026, 9, 2, 9, 0, 0)


@pytest.mark.django_db
def test_sync_api_error_leaves_that_schools_checkpoint_and_continues(school, second_school):
    """A Helcim error for one school never advances its checkpoint; the other school still syncs."""
    School.objects.filter(pk=second_school.pk).update(
        helcim_api_token='tok-second',
        helcim_last_synced_at=_utc(2026, 9, 1, 12, 0, 0),
    )

    def side_effect(self, **kwargs):
        if self.api_token == 'tok-second':
            raise HelcimAPIError('down', status_code=503)
        return [_tx(90201, 'NO-SUCH-INVOICE', '2026-09-06 10:00:00')]

    with mock.patch(LIST_TARGET, autospec=True, side_effect=side_effect), \
         mock.patch(GET_TARGET, return_value=_tx(90201, 'NO-SUCH-INVOICE', '2026-09-06 10:00:00')):
        call_command('sync_helcim_payments', stdout=StringIO(), stderr=StringIO())

    assert HelcimWebhookEvent.objects.filter(helcim_transaction_id='90201').exists()
    school.refresh_from_db()
    second_school.refresh_from_db()
    assert school.helcim_last_synced_at == _utc(2026, 9, 6, 10, 0, 0)
    assert second_school.helcim_last_synced_at == _utc(2026, 9, 1, 12, 0, 0)
