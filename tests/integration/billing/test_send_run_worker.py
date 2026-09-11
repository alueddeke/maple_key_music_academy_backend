"""
Integration tests for the send-run worker (process_invoice_send_runs --once).

Helcim + email are mocked at the invoice_sending seams; everything else —
claiming, retries, counters, run completion — runs for real against the DB.
"""
from datetime import date
from decimal import Decimal
from unittest import mock

import pytest
from django.core.management import call_command

from billing.models import (
    BillableContact,
    InvoiceSendItem,
    InvoiceSendRun,
    PreBillingInvoice,
)
from billing.models import Lesson
from billing.services.helcim_client import HelcimAPIError, HelcimInvoiceNumberExists

pytestmark = pytest.mark.django_db


HELCIM_OK = {'invoiceId': 9001, 'invoiceNumber': 'INV-9001', 'token': 'tok_test'}


@pytest.fixture
def run_with_two_invoices(school, management_user, teacher_user, django_user_model):
    invoices = []
    for i in range(2):
        student = django_user_model.objects.create_user(
            email=f'worker_student_{i}@sendrun.test',
            password='testpass123',
            user_type='student',
            first_name=f'Worker{i}',
            last_name='Student',
            school=school,
            is_approved=True,
        )
        BillableContact.objects.create(
            student=student, school=school, is_primary=True,
            first_name='Contact', last_name=f'W{i}',
            email=f'worker_contact_{i}@sendrun.test', phone='555-0400',
            street_address='1 Test St', city='Toronto', province='ON',
            postal_code='M5H 2N2', helcim_customer_id=f'cust_w{i}',
        )
        invoice = PreBillingInvoice.objects.create(
            student=student, school=school, status='draft',
            amount=Decimal('100.00'),
            period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
        )
        lesson = Lesson.objects.create(
            teacher=teacher_user, student=student, school=school,
            lesson_type='online',
            teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'),
            scheduled_date=date(2026, 6, 10 + i), duration=1.0,
            status='confirmed',
        )
        invoice.lessons.add(lesson)
        invoices.append(invoice)

    run = InvoiceSendRun.objects.create(
        school=school, period_start=date(2026, 6, 1),
        created_by=management_user, item_count=len(invoices),
    )
    InvoiceSendItem.objects.bulk_create([
        InvoiceSendItem(run=run, invoice=inv, position=pos)
        for pos, inv in enumerate(invoices)
    ])
    return run, invoices


def _mock_helcim(create_invoice=None, lookup=None):
    client = mock.Mock()
    client.create_invoice.side_effect = create_invoice or (lambda **kw: HELCIM_OK)
    client.create_customer.return_value = {'id': 999}
    # Lookup-first (MAP-185): default "Helcim holds nothing under that number".
    client.get_invoice_by_number.side_effect = lookup or (lambda number: None)
    return mock.patch(
        'billing.services.invoice_sending.HelcimClient', return_value=client
    ), client


def _mock_email(result=(True, 'sent')):
    return mock.patch(
        'billing.services.invoice_sending.PreBillingEmailService.send_payment_request',
        return_value=result,
    )


def test_worker_drains_run_and_marks_done(run_with_two_invoices):
    run, invoices = run_with_two_invoices
    helcim_patch, client = _mock_helcim()
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.status == 'done'
    assert run.sent_count == 2
    assert run.failed_count == 0
    assert run.started_at is not None and run.finished_at is not None
    assert client.create_invoice.call_count == 2
    for invoice in invoices:
        invoice.refresh_from_db()
        assert invoice.status == 'sent'
    assert set(run.items.values_list('status', flat=True)) == {'sent'}


def test_validation_failure_is_terminal_and_counted(run_with_two_invoices):
    run, invoices = run_with_two_invoices

    def create_invoice(**kwargs):
        if create_invoice.calls == 0:
            create_invoice.calls += 1
            raise HelcimAPIError('customer rejected', status_code=400)
        return HELCIM_OK
    create_invoice.calls = 0

    helcim_patch, client = _mock_helcim(create_invoice)
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.status == 'done'
    assert run.sent_count == 1
    assert run.failed_count == 1
    failed = run.items.get(status='failed')
    assert failed.attempts == 1  # 4xx never retries
    assert 'customer rejected' in failed.last_error
    # The claim is NOT released (MAP-185): the row stays sending/unknown with
    # its attempt id, so the next attempt looks the number up before creating.
    failed.invoice.refresh_from_db()
    assert failed.invoice.status == 'sending'
    assert failed.invoice.send_outcome == 'unknown'
    assert failed.invoice.send_attempt_id is not None


def test_transient_failure_retries_then_succeeds(run_with_two_invoices, monkeypatch):
    monkeypatch.setattr('billing.management.commands.process_invoice_send_runs.RETRY_BACKOFF_SECONDS', 0)
    run, _ = run_with_two_invoices

    def create_invoice(**kwargs):
        create_invoice.calls += 1
        if create_invoice.calls == 1:
            raise HelcimAPIError('Helcim server error', status_code=500)
        return HELCIM_OK
    create_invoice.calls = 0

    helcim_patch, client = _mock_helcim(create_invoice)
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.status == 'done'
    assert run.sent_count == 2
    assert run.failed_count == 0
    retried = run.items.order_by('position').first()
    assert retried.attempts == 2


def test_transient_failure_exhausts_attempts_and_fails(run_with_two_invoices, monkeypatch):
    monkeypatch.setattr('billing.management.commands.process_invoice_send_runs.RETRY_BACKOFF_SECONDS', 0)
    run, _ = run_with_two_invoices

    helcim_patch, client = _mock_helcim(
        lambda **kw: (_ for _ in ()).throw(HelcimAPIError('down', status_code=None))
    )
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.status == 'done'
    assert run.failed_count == 2
    for item in run.items.all():
        assert item.status == 'failed'
        assert item.attempts == 3


def test_invoice_sent_after_snapshot_is_skipped_not_failed(run_with_two_invoices):
    run, invoices = run_with_two_invoices
    # First invoice was sent individually between snapshot and worker pickup
    PreBillingInvoice.objects.filter(pk=invoices[0].pk).update(status='sent')

    helcim_patch, client = _mock_helcim()
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.status == 'done'
    assert run.sent_count == 1
    assert run.failed_count == 0  # skip is not a failure
    skipped = run.items.get(invoice=invoices[0])
    assert skipped.status == 'skipped'
    assert client.create_invoice.call_count == 1


def test_cancelled_run_items_stay_untouched(run_with_two_invoices, management_user, school):
    run, invoices = run_with_two_invoices
    run.items.update(status='skipped')
    InvoiceSendRun.objects.filter(pk=run.pk).update(status='cancelled')

    helcim_patch, client = _mock_helcim()
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    client.create_invoice.assert_not_called()
    for invoice in invoices:
        invoice.refresh_from_db()
        assert invoice.status == 'draft'


def test_orphaned_sending_item_recovers_and_processes(run_with_two_invoices):
    """A dead worker's 'sending' item (stale claimed_at) re-queues and sends."""
    from django.utils import timezone
    run, invoices = run_with_two_invoices
    orphan = run.items.order_by('position').first()
    InvoiceSendItem.objects.filter(pk=orphan.pk).update(
        status='sending',
        claimed_at=timezone.now() - timezone.timedelta(minutes=30),
    )
    InvoiceSendRun.objects.filter(pk=run.pk).update(status='running')

    helcim_patch, client = _mock_helcim()
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.status == 'done'
    assert run.sent_count == 2
    orphan.refresh_from_db()
    assert orphan.status == 'sent'


# ---------------------------------------------------------------------------
# MAP-185: sends are reconciled, never duplicated, never stranded
# ---------------------------------------------------------------------------

def _single_item_run(run_with_two_invoices):
    """Trim the fixture to one item so 'exactly one create across the run' is unambiguous."""
    run, invoices = run_with_two_invoices
    run.items.filter(invoice=invoices[1]).delete()
    InvoiceSendRun.objects.filter(pk=run.pk).update(item_count=1)
    return run, invoices[0]


def _accepted_store():
    """
    Simulates Helcim's side: every create records the number it was given.
    Lookups answer from that store — a create we 'never heard back from' is
    still there.
    """
    accepted = {}

    def lookup(number):
        return accepted.get(number)

    return accepted, lookup


def _new_run_for(invoice, management_user):
    run = InvoiceSendRun.objects.create(
        school=invoice.school, period_start=invoice.period_start,
        created_by=management_user, item_count=1,
    )
    InvoiceSendItem.objects.create(run=run, invoice=invoice, position=0)
    return run


def test_retry_after_create_raised_adopts_via_lookup(run_with_two_invoices, monkeypatch):
    """
    Helcim accepted the create but we never heard back (timeout). The worker's
    in-place retry looks the previous attempt's number up, adopts it, and
    creates nothing — one Helcim invoice, sent with the first id.
    """
    monkeypatch.setattr('billing.management.commands.process_invoice_send_runs.RETRY_BACKOFF_SECONDS', 0)
    run, invoice = _single_item_run(run_with_two_invoices)
    accepted, lookup = _accepted_store()

    def create_invoice(**kwargs):
        number = kwargs['invoice_number']
        accepted[number] = {'invoiceId': 7001, 'invoiceNumber': number, 'token': 'tok_7001'}
        raise HelcimAPIError('timeout after Helcim accepted', status_code=None)

    helcim_patch, client = _mock_helcim(create_invoice, lookup)
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.status == 'done'
    assert run.sent_count == 1
    assert run.failed_count == 0
    assert client.create_invoice.call_count == 1
    (first_number,) = accepted
    client.get_invoice_by_number.assert_called_once_with(first_number)
    assert first_number.startswith(f'MK{invoice.pk}-')

    invoice.refresh_from_db()
    assert invoice.status == 'sent'
    assert invoice.send_outcome == 'sent'
    assert invoice.helcim_invoice_id == '7001'
    assert invoice.helcim_invoice_number == first_number
    assert invoice.payment_token == 'tok_7001'
    assert run.items.get().attempts == 2


def test_duplicate_number_error_adopts_existing(run_with_two_invoices):
    """Helcim answers 'Invoice Number already existed' → treated as found: lookup + adopt."""
    run, invoice = _single_item_run(run_with_two_invoices)
    accepted, lookup = _accepted_store()

    def create_invoice(**kwargs):
        number = kwargs['invoice_number']
        accepted[number] = {'invoiceId': 7002, 'invoiceNumber': number, 'token': 'tok_7002'}
        raise HelcimInvoiceNumberExists('Invoice Number already existed', status_code=400)

    helcim_patch, client = _mock_helcim(create_invoice, lookup)
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.sent_count == 1
    assert run.failed_count == 0
    assert client.create_invoice.call_count == 1
    assert client.get_invoice_by_number.call_count == 1
    invoice.refresh_from_db()
    assert invoice.status == 'sent'
    assert invoice.helcim_invoice_id == '7002'
    assert invoice.helcim_invoice_number in accepted
    assert run.items.get().attempts == 1


def test_lookup_empty_creates_under_new_number(run_with_two_invoices, monkeypatch):
    """Previous attempt left nothing at Helcim → retry creates again, under a different number."""
    monkeypatch.setattr('billing.management.commands.process_invoice_send_runs.RETRY_BACKOFF_SECONDS', 0)
    run, invoice = _single_item_run(run_with_two_invoices)
    numbers = []

    def create_invoice(**kwargs):
        numbers.append(kwargs['invoice_number'])
        if len(numbers) == 1:
            raise HelcimAPIError('Helcim server error', status_code=500)
        return {'invoiceId': 7003, 'invoiceNumber': kwargs['invoice_number'], 'token': 'tok_7003'}

    helcim_patch, client = _mock_helcim(create_invoice)  # lookup → None
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.sent_count == 1
    assert client.create_invoice.call_count == 2
    client.get_invoice_by_number.assert_called_once_with(numbers[0])
    assert numbers[0] != numbers[1]
    assert all(n.startswith(f'MK{invoice.pk}-') for n in numbers)
    invoice.refresh_from_db()
    assert invoice.status == 'sent'
    assert invoice.helcim_invoice_number == numbers[1]
    assert invoice.helcim_invoice_number == f'MK{invoice.pk}-{invoice.send_attempt_id.hex[:8]}'


def test_crash_after_create_recovers_on_next_run(run_with_two_invoices, management_user):
    """
    Crash between the Helcim create and our persist: the run reports the
    failure and the invoice stays sending/unknown (never back to draft). The
    next run recovers it through lookup-first — sent with the first id, no
    second create.
    """
    run, invoice = _single_item_run(run_with_two_invoices)
    accepted, lookup = _accepted_store()

    def create_invoice(**kwargs):
        number = kwargs['invoice_number']
        accepted[number] = {'invoiceId': 7004, 'invoiceNumber': number, 'token': 'tok_7004'}
        # Helcim answered, but our side blew up before persisting (no token).
        return {'invoiceId': 7004, 'invoiceNumber': number}

    helcim_patch, client = _mock_helcim(create_invoice, lookup)
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run.refresh_from_db()
    assert run.status == 'done'
    assert run.failed_count == 1
    assert run.items.get().status == 'failed'
    invoice.refresh_from_db()
    assert invoice.status == 'sending'
    assert invoice.send_outcome == 'unknown'
    first_attempt = invoice.send_attempt_id
    assert first_attempt is not None
    assert client.create_invoice.call_count == 1

    run2 = _new_run_for(invoice, management_user)
    with helcim_patch, _mock_email():
        call_command('process_invoice_send_runs', '--once')

    run2.refresh_from_db()
    assert run2.status == 'done'
    assert run2.sent_count == 1
    assert run2.failed_count == 0
    assert client.create_invoice.call_count == 1
    invoice.refresh_from_db()
    assert invoice.status == 'sent'
    assert invoice.send_outcome == 'sent'
    assert invoice.helcim_invoice_id == '7004'
    assert invoice.helcim_invoice_number == f'MK{invoice.pk}-{first_attempt.hex[:8]}'
    assert invoice.send_attempt_id != first_attempt  # the claim rotated it
