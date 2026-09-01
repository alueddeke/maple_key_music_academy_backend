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
from billing.services.helcim_client import HelcimAPIError

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


def _mock_helcim(create_invoice=None):
    client = mock.Mock()
    client.create_invoice.side_effect = create_invoice or (lambda **kw: HELCIM_OK)
    client.create_customer.return_value = {'id': 999}
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
    # The failed invoice's claim was released — sendable again individually
    failed.invoice.refresh_from_db()
    assert failed.invoice.status == 'draft'


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
