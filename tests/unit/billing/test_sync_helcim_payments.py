"""
Unit tests for the sync_helcim_payments management command — pull-based
recovery for payments whose webhooks never arrived.
"""

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command

from billing.models import (
    HelcimWebhookEvent,
    PreBillingInvoice,
    StudentCreditAccount,
    CreditTransaction,
    BillableContact,
)

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
