"""
Unit tests for the sync_helcim_ach management command (MAP-217) — the bank
(ACH/EFT) rail. Helcim sends no bank webhooks, so this poll is the only way a
bank payment reaches the ledger.

Helcim is mocked at the client boundary (`list_ach_transactions`); the command
and the credit path run for real against the DB.

`ach_row` is the one sample of Helcim's row in this file. It is built from
Helcim's documentation, not from an observed row (none existed on 2026-10-05,
MAP-270). When a real row arrives, correct `ach_row` and the shape block at the
top of sync_helcim_ach.py together; every test below reads Helcim's values
through those two places.
"""

import logging
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone
from prometheus_client import REGISTRY

from billing.management.commands import sync_helcim_ach as command_module
from billing.management.commands.sync_helcim_payments import FIRST_RUN_LOOKBACK_DAYS
from billing.models import (
    CreditTransaction,
    HelcimWebhookEvent,
    PreBillingInvoice,
    School,
    StudentCreditAccount,
)
from billing.services.helcim_client import ACH_PAGE_LIMIT, HelcimAPIError, HelcimClient
from billing.services.webhook_processing import (
    ACH_REFUSED_STATUSES,
    ACH_WAITING_STATUSES,
    ALERT_STATES,
    RETRYABLE_STATES,
    process_webhook_event,
)

ACH_LIST = 'billing.services.helcim_client.HelcimClient.list_ach_transactions'
CARD_LIST = 'billing.services.helcim_client.HelcimClient.list_card_transactions'
CARD_GET = 'billing.services.webhook_processing.HelcimClient.get_card_transaction'
HTTP_GET = 'billing.services.helcim_client.requests.get'

DAY_ONE = '2026-10-01 12:00:00'
DAY_TWO = '2026-10-02 09:30:00'
DAY_THREE = '2026-10-03 15:45:00'


def _auth_value(name):
    """Helcim's statusAuth value for a canonical name, read from the command's table."""
    return next(value for value, known in command_module.STATUS_AUTH_NAMES.items() if known == name)


def _unlisted(values):
    """A value Helcim's documentation does not list."""
    return max(values) + 90


def ach_row(tx_id, invoice_number='', amount='60.00', status='APPROVED', created=DAY_ONE, **overrides):
    """
    One row of GET /v2/ach/transactions as Helcim documents it (devdocs
    "ach-payments" example + the getmanyachtransactions schema).
    """
    row = {
        command_module.ROW_ID_KEY: tx_id,
        'merchantId': 208967,
        'orderId': 37281729,
        command_module.ROW_DATE_CREATED_KEY: created,
        command_module.ROW_STATUS_AUTH_KEY: _auth_value(status),
        'statusClearing': 0,
        'userId': 0,
        'batchId': 0,
        'bankAccountId': 41992,
        'bankAccountL4L4': 23190563,
        command_module.ROW_TRANSACTION_TYPE_KEY: next(iter(command_module.DEBIT_TRANSACTION_TYPES)),
        command_module.ROW_AMOUNT_KEY: float(amount),
        'currency': 1,
        'approvalCode': '',
        'test': 0,
        'acquirerTransactionId': '',
        'responseMessage': '',
        'payFacTransactionId': 0,
        'originalTransactionId': 0,
        'statusBatch': 1,
        'dateClosed': '0000-00-00 00:00:00',
        'customerCode': 'CST1000',
        command_module.ROW_INVOICE_NUMBER_KEY: invoice_number,
    }
    row.update(overrides)
    return row


def _invoice_and_account(school, student_user, number, **invoice_fields):
    invoice = PreBillingInvoice.objects.create(
        student=student_user,
        school=school,
        status='sent',
        amount=Decimal('60.00'),
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        helcim_invoice_number=number,
        **invoice_fields,
    )
    account = StudentCreditAccount.objects.create(
        student=student_user, school=school, balance=Decimal('0.00')
    )
    return invoice, account


def _sync(rows, *args):
    """Run the command with Helcim answering `rows`; returns (client mock, output)."""
    out = StringIO()
    with mock.patch(ACH_LIST, return_value=rows) as listed:
        call_command('sync_helcim_ach', *args, stdout=out, stderr=out)
    return listed, out.getvalue()


def _ach_event(tx_id):
    return HelcimWebhookEvent.objects.get(rail='ach', helcim_transaction_id=str(tx_id))


def _card_payment(tx_id, invoice_number, amount):
    """A card webhook event run through the standard path (card API mocked)."""
    event = HelcimWebhookEvent.objects.create(
        helcim_transaction_id=str(tx_id),
        raw_payload={'id': str(tx_id), 'type': 'cardTransaction'},
        invoice_id='',
        amount=Decimal('0.00'),
    )
    tx = {'invoiceNumber': invoice_number, 'amount': str(amount),
          'status': 'APPROVED', 'type': 'purchase'}
    with mock.patch(CARD_GET, return_value=tx):
        process_webhook_event(event)
    return event


def _scheduler_tick(rows):
    """One scheduler tick with Helcim's bank list answering `rows` (cards quiet)."""
    with mock.patch(ACH_LIST, return_value=rows), \
         mock.patch(CARD_LIST, return_value=[]), \
         mock.patch(CARD_GET):
        call_command('run_scheduler', '--once', stdout=StringIO())


def _checkpoint(school):
    return School.objects.get(pk=school.pk).helcim_ach_last_synced_at


def _utc(text):
    return datetime.strptime(text, '%Y-%m-%d %H:%M:%S').replace(tzinfo=dt_timezone.utc)


# --- credit --------------------------------------------------------------------

@pytest.mark.django_db
def test_approved_bank_payment_credits_the_invoice_once(school, student_user):
    """APPROVED → one ledger row for the invoice amount, invoice paid by bank; a second run adds nothing."""
    invoice, account = _invoice_and_account(school, student_user, 'MK1-bank')
    rows = [ach_row(5001, 'MK1-bank', invoice.amount)]

    _sync(rows)

    event = _ach_event(5001)
    assert event.processing_status == 'credited'
    assert event.school == school
    assert set(event.raw_payload) == {'id', 'rail', 'source'}  # no bank data stored
    ledger_row = CreditTransaction.objects.get()
    assert ledger_row.type == 'pre_billing_payment'
    assert ledger_row.amount == invoice.amount
    assert ledger_row.source_event == event
    invoice.refresh_from_db()
    assert (invoice.status, invoice.paid_via) == ('paid', 'bank')
    account.refresh_from_db()
    assert account.balance == invoice.amount

    _sync(rows)

    assert CreditTransaction.objects.count() == 1
    assert HelcimWebhookEvent.objects.count() == 1
    account.refresh_from_db()
    assert account.balance == invoice.amount


@pytest.mark.django_db
def test_card_payment_marks_the_invoice_paid_via_card(school, student_user):
    invoice, _ = _invoice_and_account(school, student_user, 'MK2-card')

    event = _card_payment(6001, 'MK2-card', invoice.amount)

    assert event.rail == 'card'
    invoice.refresh_from_db()
    assert (invoice.status, invoice.paid_via) == ('paid', 'card')


# --- waiting on the bank ---------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('waiting_status', sorted(
    ACH_WAITING_STATUSES & set(command_module.STATUS_AUTH_NAMES.values())
))
def test_pending_bank_payment_waits_then_credits_when_approved(school, student_user, waiting_status):
    """Pending → no credit, no alert, not retried; the same id APPROVED on a later run → credited once."""
    invoice, account = _invoice_and_account(school, student_user, 'MK3-wait')

    _scheduler_tick([ach_row(5002, 'MK3-wait', invoice.amount, status=waiting_status)])

    event = _ach_event(5002)
    assert event.processing_status == 'awaiting_bank'
    assert event.processing_status not in RETRYABLE_STATES | ALERT_STATES
    assert CreditTransaction.objects.count() == 0
    assert REGISTRY.get_sample_value('maplekey_webhook_events_failed_15m') == 0
    HelcimWebhookEvent.objects.filter(pk=event.pk).update(
        received_at=timezone.now() - timedelta(hours=2))
    _scheduler_tick([ach_row(5002, 'MK3-wait', invoice.amount, status=waiting_status)])
    assert REGISTRY.get_sample_value('maplekey_webhook_events_unresolved_1h') == 0
    invoice.refresh_from_db()
    assert invoice.status == 'sent'

    _sync([ach_row(5002, 'MK3-wait', invoice.amount, status='APPROVED')])

    event.refresh_from_db()
    assert event.processing_status == 'credited'
    assert CreditTransaction.objects.count() == 1
    account.refresh_from_db()
    assert account.balance == invoice.amount
    invoice.refresh_from_db()
    assert (invoice.status, invoice.paid_via) == ('paid', 'bank')


@pytest.mark.django_db
def test_pending_bank_payment_that_is_then_declined_is_never_credited(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, 'MK4-wait')
    _sync([ach_row(5003, 'MK4-wait', invoice.amount, status='PENDING')])

    _sync([ach_row(5003, 'MK4-wait', invoice.amount, status='DECLINED')])

    assert _ach_event(5003).processing_status == 'not_approved'
    assert CreditTransaction.objects.count() == 0
    account.refresh_from_db()
    assert account.balance == Decimal('0.00')


@pytest.mark.django_db
def test_bank_payment_waiting_past_the_warning_age_is_logged(school, student_user, caplog):
    invoice, _ = _invoice_and_account(school, student_user, 'MK5-stale')
    rows = [ach_row(5004, 'MK5-stale', invoice.amount, status='PENDING')]
    _sync(rows)
    HelcimWebhookEvent.objects.filter(rail='ach').update(
        received_at=timezone.now() - command_module.AWAITING_WARN_AFTER - timedelta(hours=1))

    with caplog.at_level(logging.WARNING, logger=command_module.__name__):
        _sync(rows)

    assert 'still awaiting the bank' in caplog.text
    assert _ach_event(5004).processing_status == 'awaiting_bank'


# --- never credited ----------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize('refused_status', sorted(
    ACH_REFUSED_STATUSES & set(command_module.STATUS_AUTH_NAMES.values())
))
def test_refused_bank_payment_is_recorded_without_credit(school, student_user, refused_status):
    invoice, account = _invoice_and_account(school, student_user, 'MK6-no')

    _sync([ach_row(5005, 'MK6-no', invoice.amount, status=refused_status)])

    event = _ach_event(5005)
    assert event.processing_status == 'not_approved'
    assert event.processing_status not in ALERT_STATES
    assert CreditTransaction.objects.count() == 0
    invoice.refresh_from_db()
    assert (invoice.status, invoice.paid_via) == ('sent', '')


@pytest.mark.django_db
def test_unlisted_authorization_status_alerts_and_does_not_credit(school, student_user):
    """A statusAuth value outside the documented table → needs_attention (alert state), no credit."""
    invoice, account = _invoice_and_account(school, student_user, 'MK7-odd')
    row = ach_row(5006, 'MK7-odd', invoice.amount)
    row[command_module.ROW_STATUS_AUTH_KEY] = _unlisted(command_module.STATUS_AUTH_NAMES)

    _sync([row])

    event = _ach_event(5006)
    assert event.processing_status == 'needs_attention'
    assert event.processing_status in ALERT_STATES
    assert CreditTransaction.objects.count() == 0


@pytest.mark.django_db
def test_unlisted_transaction_type_alerts_and_does_not_credit(school, student_user):
    """An approved row that is not a known debit (e.g. a credit back to the payer) never credits."""
    invoice, account = _invoice_and_account(school, student_user, 'MK8-odd')
    row = ach_row(5007, 'MK8-odd', invoice.amount)
    row[command_module.ROW_TRANSACTION_TYPE_KEY] = _unlisted(command_module.DEBIT_TRANSACTION_TYPES)

    _sync([row])

    assert _ach_event(5007).processing_status == 'needs_attention'
    assert CreditTransaction.objects.count() == 0
    account.refresh_from_db()
    assert account.balance == Decimal('0.00')


@pytest.mark.django_db
def test_bank_payment_on_an_invoice_a_card_already_covered_needs_attention(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, 'MK9-both')
    _card_payment(6002, 'MK9-both', invoice.amount)

    _sync([ach_row(5008, 'MK9-both', invoice.amount)])

    assert _ach_event(5008).processing_status == 'needs_attention'
    assert CreditTransaction.objects.count() == 1
    account.refresh_from_db()
    assert account.balance == invoice.amount
    invoice.refresh_from_db()
    assert invoice.paid_via == 'card'


@pytest.mark.django_db
def test_card_payment_on_an_invoice_a_bank_payment_already_covered_needs_attention(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, 'MK10-both')
    _sync([ach_row(5009, 'MK10-both', invoice.amount)])

    card_event = _card_payment(6003, 'MK10-both', invoice.amount)

    assert card_event.processing_status == 'needs_attention'
    assert CreditTransaction.objects.count() == 1
    account.refresh_from_db()
    assert account.balance == invoice.amount
    invoice.refresh_from_db()
    assert invoice.paid_via == 'bank'


@pytest.mark.django_db
def test_bank_payment_on_a_superseded_invoice_number_needs_attention(school, student_user):
    invoice, account = _invoice_and_account(
        school, student_user, 'MK11-new', previous_helcim_invoice_number='MK11-old')

    _sync([ach_row(5010, 'MK11-old', invoice.amount)])

    assert _ach_event(5010).processing_status == 'needs_attention'
    assert CreditTransaction.objects.count() == 0
    invoice.refresh_from_db()
    assert invoice.status == 'sent'


@pytest.mark.django_db
def test_unknown_invoice_number_is_no_invoice_and_counted_by_the_alert_gauge(school, student_user):
    _scheduler_tick([ach_row(5011, 'MK-nobody-has-this', '60.00')])

    assert _ach_event(5011).processing_status == 'no_invoice'
    assert REGISTRY.get_sample_value('maplekey_webhook_events_failed_15m') == 1
    assert CreditTransaction.objects.count() == 0


@pytest.mark.django_db
def test_bank_event_in_a_retryable_state_is_retried_without_the_card_api(school, student_user):
    """no_invoice → the invoice appears → retry_webhook_events credits from the stored fields."""
    _sync([ach_row(5012, 'MK12-late', '60.00')])
    assert _ach_event(5012).processing_status == 'no_invoice'
    invoice, account = _invoice_and_account(school, student_user, 'MK12-late')

    with mock.patch(CARD_GET) as card_api:
        call_command('retry_webhook_events', stdout=StringIO())

    assert card_api.call_count == 0
    assert _ach_event(5012).processing_status == 'credited'
    account.refresh_from_db()
    assert account.balance == invoice.amount
    invoice.refresh_from_db()
    assert invoice.paid_via == 'bank'


# --- identity ----------------------------------------------------------------------

@pytest.mark.django_db
def test_bank_and_card_transactions_with_the_same_id_are_separate_events(school, student_user):
    invoice, _ = _invoice_and_account(school, student_user, 'MK13-id')
    _card_payment(7777, 'MK13-id', invoice.amount)

    _sync([ach_row(7777, 'MK-other', '60.00', status='DECLINED')])

    rails = HelcimWebhookEvent.objects.filter(helcim_transaction_id='7777').values_list('rail', flat=True)
    assert sorted(rails) == ['ach', 'card']


# --- checkpoint ----------------------------------------------------------------------

@pytest.mark.django_db
def test_checkpoint_stays_put_after_an_api_error(school):
    before = _utc(DAY_ONE)
    School.objects.filter(pk=school.pk).update(helcim_ach_last_synced_at=before)

    out = StringIO()
    with mock.patch(ACH_LIST, side_effect=HelcimAPIError('down', status_code=503)):
        call_command('sync_helcim_ach', stdout=out, stderr=out)

    assert _checkpoint(school) == before
    assert HelcimWebhookEvent.objects.count() == 0
    assert 'checkpoint unchanged' in out.getvalue()


@pytest.mark.django_db
def test_checkpoint_advances_to_the_newest_row_when_nothing_is_waiting(school):
    _sync([
        ach_row(5020, 'MK-a', '60.00', status='DECLINED', created=DAY_ONE),
        ach_row(5021, 'MK-b', '60.00', status='DECLINED', created=DAY_THREE),
        ach_row(5022, 'MK-c', '60.00', status='DECLINED', created=DAY_TWO),
    ])

    assert _checkpoint(school) == _utc(DAY_THREE)


@pytest.mark.django_db
def test_checkpoint_is_held_at_the_oldest_row_still_waiting_on_the_bank(school):
    """So the next run asks Helcim for the waiting row again."""
    rows = [
        ach_row(5023, 'MK-a', '60.00', status='DECLINED', created=DAY_ONE),
        ach_row(5024, 'MK-b', '60.00', status='PENDING', created=DAY_TWO),
        ach_row(5025, 'MK-c', '60.00', status='DECLINED', created=DAY_THREE),
    ]
    _sync(rows)
    assert _checkpoint(school) == _utc(DAY_TWO)

    listed, _ = _sync(rows[1:])

    assert listed.call_args.kwargs['date_from'] == _utc(DAY_TWO).date()
    assert _checkpoint(school) == _utc(DAY_TWO)


@pytest.mark.django_db
def test_first_run_looks_back_the_configured_number_of_days(school):
    earliest = (timezone.now() - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)).date()

    listed, _ = _sync([])

    latest = (timezone.now() - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)).date()
    assert listed.call_args.kwargs['date_from'] in {earliest, latest}
    assert _checkpoint(school) is None


@pytest.mark.django_db
def test_row_without_an_id_is_skipped_and_holds_the_checkpoint(school):
    row = ach_row(5026, 'MK-a', '60.00', status='DECLINED')
    del row[command_module.ROW_ID_KEY]

    _, output = _sync([row, ach_row(5027, 'MK-b', '60.00', status='DECLINED', created=DAY_TWO)])

    assert list(HelcimWebhookEvent.objects.values_list('helcim_transaction_id', flat=True)) == ['5027']
    assert _checkpoint(school) is None
    assert 'unreadable' in output


@pytest.mark.django_db
def test_dry_run_records_nothing(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, 'MK14-dry')

    _, output = _sync([ach_row(5028, 'MK14-dry', invoice.amount)], '--dry-run')

    assert HelcimWebhookEvent.objects.count() == 0
    assert CreditTransaction.objects.count() == 0
    assert _checkpoint(school) is None
    assert '1 new' in output


@pytest.mark.django_db
def test_a_full_page_makes_the_command_ask_for_the_next_one(school):
    first_page = [
        ach_row(8000 + n, 'MK-page', '60.00', status='DECLINED') for n in range(ACH_PAGE_LIMIT)
    ]
    second_page = [ach_row(9000, 'MK-page', '60.00', status='DECLINED')]

    out = StringIO()
    with mock.patch(ACH_LIST, side_effect=[first_page, second_page]) as listed:
        call_command('sync_helcim_ach', stdout=out, stderr=out)

    assert [call.kwargs['page'] for call in listed.call_args_list] == [1, 2]
    assert HelcimWebhookEvent.objects.filter(rail='ach').count() == ACH_PAGE_LIMIT + 1


# --- client boundary ------------------------------------------------------------------

def _http_response(status_code, body=None):
    response = mock.Mock(ok=200 <= status_code < 300, status_code=status_code)
    response.content = b'' if body is None else b'x'
    response.json.return_value = body
    response.text = ''
    return response


@pytest.mark.django_db
def test_client_reads_no_content_as_an_empty_list(school):
    with mock.patch(HTTP_GET, return_value=_http_response(204)) as http_get:
        rows = HelcimClient(school=school).list_ach_transactions(date_from=date(2026, 10, 1), page=1)

    assert rows == []
    sent = http_get.call_args.kwargs['params']
    assert sent['startDate'] == '2026-10-01'
    assert sent['limit'] == ACH_PAGE_LIMIT
    assert sent['page'] == 1
    assert http_get.call_args.args[0].endswith('/ach/transactions')


@pytest.mark.django_db
@pytest.mark.parametrize('envelope', ['bare', 'transactions', 'data'])
def test_client_returns_the_rows_whatever_the_envelope(school, envelope):
    rows = [ach_row(5030, 'MK-env', '60.00')]
    body = rows if envelope == 'bare' else {envelope: rows}

    with mock.patch(HTTP_GET, return_value=_http_response(200, body)):
        assert HelcimClient(school=school).list_ach_transactions() == rows


@pytest.mark.django_db
def test_client_raises_on_an_error_response(school):
    with mock.patch(HTTP_GET, return_value=_http_response(401)):
        with pytest.raises(HelcimAPIError):
            HelcimClient(school=school).list_ach_transactions()
