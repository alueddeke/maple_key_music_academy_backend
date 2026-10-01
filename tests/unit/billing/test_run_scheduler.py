"""
Unit tests for run_scheduler (MAP-154) — the unattended reconciliation loop.

One tick = retry_webhook_events (every 15 min), sync_helcim_payments (once
per UTC day at/after 03:00), and the unresolved + failed-15m gauges. Helcim is
mocked at the client seams; the commands run for real against the DB.
"""

import logging
import signal
import threading
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
from billing.services.webhook_processing import ALERT_STATES

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


def _processed(event, ago):
    """Stamp processed_at `ago` in the past (the processing path sets it to now)."""
    HelcimWebhookEvent.objects.filter(pk=event.pk).update(processed_at=timezone.now() - ago)


def _tick():
    call_command('run_scheduler', '--once', stdout=StringIO())


def _failed_gauge():
    return REGISTRY.get_sample_value('maplekey_webhook_events_failed_15m')


def test_sigterm_stops_the_idle_loop_within_two_seconds(caplog):
    """
    MAP-215: SIGTERM must interrupt the 60 s idle wait, not be noticed after
    it. handle(once=False) runs in a thread with the tick and the metrics
    server patched out; the stop request lands while the loop is idle and
    the thread must be gone within 2 s with the usual last log line.
    """
    from billing.management.commands.run_scheduler import Command

    cmd = Command()
    started = threading.Event()

    with mock.patch.object(Command, '_tick', side_effect=started.set) as tick, \
         mock.patch('billing.management.commands.run_scheduler.start_http_server') as server, \
         mock.patch('billing.management.commands.run_scheduler.signal.signal'), \
         caplog.at_level(logging.INFO, logger='billing.management.commands.run_scheduler'):
        worker = threading.Thread(target=cmd.handle, kwargs={'once': False}, daemon=True)
        worker.start()
        assert started.wait(2), 'first tick never ran'

        cmd._request_stop(signal.SIGTERM, None)
        worker.join(timeout=2)

    assert not worker.is_alive(), 'scheduler did not exit within 2 s of SIGTERM'
    assert tick.call_count >= 1
    assert server.call_count == 1  # once=False still starts the metrics server
    assert 'Scheduler stopped' in caplog.text


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


# --- maplekey_webhook_events_failed_15m (MAP-231) ---------------------------
# The webhook-failures alert reads this gauge: a count from the DB, so one
# event is enough to fire (the per-process counter's increase() missed it).
# Helcim stays down in these ticks, so the retry leaves retryable events in
# an alert state and re-stamps processed_at, as it does in prod.

HELCIM_DOWN = HelcimAPIError('down', status_code=503)


@pytest.mark.django_db
def test_failed_gauge_counts_recent_alert_event(school):
    """One needs_attention event processed a minute ago → gauge 1."""
    _processed(_event('tx-na-recent', timedelta(minutes=2), 'needs_attention'), timedelta(minutes=1))

    with mock.patch(GET_TARGET, side_effect=HELCIM_DOWN), \
         mock.patch(LIST_TARGET, return_value=[]):
        _tick()

    assert _failed_gauge() == 1


@pytest.mark.django_db
def test_failed_gauge_ignores_old_and_non_alert_events(school):
    """
    Outside the window (terminal, so the retry does not re-stamp it) or not in
    ALERT_STATES → not counted.
    """
    _processed(_event('tx-na-old', timedelta(minutes=25), 'needs_attention'), timedelta(minutes=20))
    for status in ('credited', 'not_approved', 'non_purchase'):
        assert status not in ALERT_STATES
        _processed(_event(f'tx-{status}', timedelta(minutes=2), status), timedelta(minutes=1))

    with mock.patch(GET_TARGET, side_effect=HELCIM_DOWN), \
         mock.patch(LIST_TARGET, return_value=[]):
        _tick()

    assert _failed_gauge() == 0


@pytest.mark.django_db
def test_failed_gauge_counts_every_alert_state(school):
    """One recent event per ALERT_STATES member → all counted."""
    for status in ALERT_STATES:
        _processed(_event(f'tx-alert-{status}', timedelta(minutes=2), status), timedelta(minutes=1))

    with mock.patch(GET_TARGET, side_effect=HELCIM_DOWN), \
         mock.patch(LIST_TARGET, return_value=[]):
        _tick()

    assert _failed_gauge() == len(ALERT_STATES)
