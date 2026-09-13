"""
Unit tests for run_scheduler (MAP-154) — the unattended reconciliation loop.

One tick = retry_webhook_events (every 15 min), sync_helcim_payments (once
per UTC day at/after 03:00), and the unresolved-events gauge. Helcim is
mocked at the client seams; the commands run for real against the DB.
"""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone
from prometheus_client import REGISTRY

from billing.models import (
    CreditTransaction,
    HelcimWebhookEvent,
    PreBillingInvoice,
    StudentCreditAccount,
)
from billing.services.helcim_client import HelcimAPIError

GET_TARGET = 'billing.services.webhook_processing.HelcimClient.get_card_transaction'
LIST_TARGET = 'billing.services.helcim_client.HelcimClient.list_card_transactions'
NOW_TARGET = 'billing.management.commands.run_scheduler.timezone.now'


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


def _event(tx_id, age, processing_status='enrichment_failed'):
    """A webhook event received `age` ago in the given state (received_at is auto_now_add)."""
    event = HelcimWebhookEvent.objects.create(
        helcim_transaction_id=tx_id,
        raw_payload={'id': tx_id, 'type': 'cardTransaction'},
        invoice_id='',
        amount=Decimal('0.00'),
        processing_status=processing_status,
    )
    HelcimWebhookEvent.objects.filter(pk=event.pk).update(received_at=timezone.now() - age)
    return event


def _tick():
    call_command('run_scheduler', '--once', stdout=StringIO())


@pytest.mark.django_db
def test_one_tick_retries_stuck_event(school, student_user):
    """enrichment_failed + Helcim back up → one tick credits it (retry_webhook_events ran)."""
    invoice, account = _invoice_and_account(school, student_user, 'INV-SCHED-1')
    event = _event('tx-sched-1', timedelta(minutes=5))
    tx = {'invoiceNumber': 'INV-SCHED-1', 'amount': '60.00',
          'status': 'APPROVED', 'type': 'purchase'}

    with mock.patch(GET_TARGET, return_value=tx), \
         mock.patch(LIST_TARGET, return_value=[]):
        _tick()

    event.refresh_from_db()
    assert event.processing_status == 'credited'
    account.refresh_from_db()
    assert account.balance == Decimal('60.00')
    invoice.refresh_from_db()
    assert invoice.status == 'paid'
    assert CreditTransaction.objects.count() == 1


@pytest.mark.django_db
def test_gauge_counts_unresolved_older_than_one_hour(school):
    """
    Gauge = retryable events received more than 1h ago. Mixed ages: two old
    retryable, one fresh retryable, one old terminal → 2. Helcim stays down
    so the retry leaves them unresolved.
    """
    _event('tx-old-1', timedelta(hours=2))
    _event('tx-old-2', timedelta(hours=3), 'no_invoice')
    _event('tx-fresh', timedelta(minutes=30))
    _event('tx-done', timedelta(hours=2), 'credited')

    with mock.patch(GET_TARGET, side_effect=HelcimAPIError('down', status_code=503)), \
         mock.patch(LIST_TARGET, return_value=[]):
        _tick()

    assert REGISTRY.get_sample_value('maplekey_webhook_events_unresolved_1h') == 2
    assert REGISTRY.get_sample_value('maplekey_scheduler_last_tick_timestamp') > 0
    assert HelcimWebhookEvent.objects.filter(
        processing_status='enrichment_failed'
    ).count() == 3  # the retry ran and Helcim was down: nothing resolved


@pytest.mark.django_db
@pytest.mark.parametrize('hour, expected_calls', [(4, 1), (2, 0)])
def test_sync_runs_once_per_day_after_0300_utc(school, hour, expected_calls):
    """Daily sync is due at/after 03:00 UTC (one provider list call per school), not before."""
    frozen = datetime(2026, 9, 13, hour, 0, 0, tzinfo=dt_timezone.utc)

    with mock.patch(NOW_TARGET, return_value=frozen), \
         mock.patch(LIST_TARGET, return_value=[]) as mock_list, \
         mock.patch(GET_TARGET):
        _tick()

    assert mock_list.call_count == expected_calls
