"""
Regression suite for the 2026-09-07 audit (MAP-193): one named test per
reproduced finding #1–#9.

Each test reproduces the finding as the audit stated it, against today's
fixtures, and asserts the behaviour the fix guarantees — HTTP status and body,
DB row state, ledger totals, calls made to the Helcim client. Amounts and rates
come from fixtures, never literals. Helcim is mocked at the client seam the
code under test uses; nothing here asserts Helcim/DRF/Django semantics.

Every test failed against backend e5dfbe9 (before the P0/P1 fixes) — see the
MAP-193 PR for the per-test record. Finding #4 (MAP-196, multi-school
settlement) is still open and is marked xfail(strict=True).

Run alone with: pytest -k audit_2026_09_07

Testing notes
  * #3 and #7 race two DB connections: @pytest.mark.django_db(transaction=True)
    and Postgres only (select_for_update is a no-op on SQLite).
  * Code added by the fixes (run_scheduler, fee_amount, ...) is referenced only
    inside test bodies, so the module itself imports on pre-fix code.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, time
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.urls import reverse
from rest_framework.test import APIClient

from billing.models import (
    BatchLessonItem,
    BillableContact,
    CreditTransaction,
    HelcimWebhookEvent,
    Invoice,
    InvoiceSendItem,
    InvoiceSendRun,
    Lesson,
    MonthlyInvoiceBatch,
    PreBillingInvoice,
    RecurringLessonsSchedule,
    StudentCreditAccount,
)
from billing.services.helcim_client import HelcimAPIError
from billing.services.webhook_processing import process_webhook_event

User = get_user_model()

# Balance effect of each ledger type (MAP-186): the only balance-moving types.
BALANCE_EFFECT = {'pre_billing_payment': 1, 'waived_rollover': 1, 'lesson_charge': -1}


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _client(user):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _student(school, email, **extra):
    return User.objects.create_user(
        email=email, password='testpass123', user_type='student',
        first_name='Audit', last_name='Student', school=school, is_approved=True, **extra,
    )


def _contact(student, customer_id=''):
    return BillableContact.objects.create(
        student=student, school=student.school, contact_type='parent', is_primary=True,
        first_name='Audit', last_name='Contact', email=f'contact_{student.pk}@audit.test',
        phone='416-555-0100', street_address='1 Audit St', city='Toronto', province='ON',
        postal_code='M5H 2N2', helcim_customer_id=customer_id,
    )


def _sent_invoice(student, number, amount):
    return PreBillingInvoice.objects.create(
        student=student, school=student.school, status='sent', amount=amount,
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31),
        helcim_invoice_number=number,
    )


def _account(student, balance=Decimal('0.00')):
    return StudentCreditAccount.objects.create(student=student, school=student.school, balance=balance)


def _enriched_event(tx_id, number, amount, status='pending', school=None):
    """A webhook event past enrichment (no Helcim call needed), still retryable."""
    return HelcimWebhookEvent.objects.create(
        helcim_transaction_id=tx_id, raw_payload={'id': tx_id, 'type': 'cardTransaction'},
        invoice_id=number, amount=amount, transaction_status='APPROVED',
        transaction_type='purchase', processing_status=status, school=school,
    )


def _billable_lessons(student, teacher, count):
    """
    Confirmed lessons at the school's stored rates. A student's first-ever
    lesson becomes a trial, so one completed lesson is seeded first.
    """
    Lesson.objects.create(
        teacher=teacher, student=student, school=student.school, lesson_type='online',
        is_trial=True, teacher_rate=Decimal('0.00'), student_rate=Decimal('0.00'),
        scheduled_date=date(2026, 5, 6), duration=1.0, status='completed',
    )
    lessons = [
        Lesson.objects.create(
            teacher=teacher, student=student, school=student.school, lesson_type='online',
            scheduled_date=date(2026, 6, 3 + 7 * i), duration=1.0, status='confirmed',
        )
        for i in range(count)
    ]
    for lesson in lessons:
        lesson.refresh_from_db()
    return lessons


def _charge(lesson):
    return (Decimal(str(lesson.student_rate)) * Decimal(str(lesson.duration))).quantize(Decimal('0.01'))


def _batch_item(batch, student, school_settings, status='completed', day=15):
    return BatchLessonItem.objects.create(
        batch=batch, student=student,
        scheduled_date=date(batch.year, batch.month, day), start_time=time(10, 0),
        duration=Decimal('1.0'), lesson_type='online',
        teacher_rate=school_settings.online_teacher_rate,
        student_rate=school_settings.online_student_rate,
        status=status,
    )


def _ledger_sum(account):
    rows = CreditTransaction.objects.filter(account=account)
    return sum((BALANCE_EFFECT.get(r.type, 0) * r.amount for r in rows), Decimal('0.00'))


def _race(fn, n=2):
    """Run fn n times concurrently, each on its own DB connection."""
    barrier = threading.Barrier(n)

    def _go():
        connection.close()
        barrier.wait(timeout=10)
        try:
            return fn()
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(_go) for _ in range(n)]
        return [f.result(timeout=30) for f in futures]


# ---------------------------------------------------------------------------
# Finding #1 — MAP-177 (+ MAP-178)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_finding_01_student_self_update_cannot_change_role_or_school(student_user, second_school):
    """Audit 2026-09-07 finding #1 (fix: MAP-177): a student updating their own record cannot change role, school or admin flags."""
    client = _client(student_user)
    # A complete, otherwise valid profile body — only the privileged keys are hostile.
    escalation = {
        'email': student_user.email, 'first_name': student_user.first_name,
        'last_name': student_user.last_name, 'password': 'Escalate!123',
        'user_type': 'management', 'school': second_school.id,
        'is_approved': True, 'is_staff': True, 'is_superuser': True,
    }
    columns = ('user_type', 'school_id', 'is_staff', 'is_superuser', 'password')
    before = User.objects.values(*columns).get(pk=student_user.pk)

    for send in (client.put, client.patch):
        response = send(f'/api/billing/students/{student_user.pk}/', escalation, format='json')
        assert not 200 <= response.status_code < 300, response.status_code

    after = User.objects.values(*columns).get(pk=student_user.pk)
    assert after == before


# ---------------------------------------------------------------------------
# Finding #2 — MAP-179 + MAP-178 (+ MAP-203)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_finding_02_teacher_one_off_cannot_set_rates_notes_or_foreign_student_and_legacy_routes_404(
    teacher_user, student_user, management_user, school, second_school, school_settings,
):
    """Audit 2026-09-07 finding #2 (fix: MAP-179, MAP-178): a teacher's one-off lesson cannot carry its own rates, admin notes or another school's student, and the legacy generic routes no longer exist."""
    student_user.assigned_teachers.add(teacher_user)
    foreign = _student(second_school, 'foreign@audit.test')
    foreign.assigned_teachers.add(teacher_user)
    batch = MonthlyInvoiceBatch.objects.create(teacher=teacher_user, school=school, month=9, year=2026, status='draft')
    teacher = _client(teacher_user)
    url = reverse('batch_add_lesson', kwargs={'batch_id': batch.id})

    def payload(student, **extra):
        return {
            'student': student.id, 'scheduled_date': '2026-09-03', 'start_time': '14:00:00',
            'duration': 1.0, 'lesson_type': 'in_person', 'status': 'completed',
            'teacher_notes': 'Scales',
        } | extra

    attempts = [
        payload(student_user, teacher_rate=str(school_settings.online_teacher_rate * 100)),
        payload(student_user, student_rate=str(-school_settings.online_student_rate)),
        payload(student_user, admin_notes='teacher-written admin note'),
        payload(foreign),
    ]
    for body in attempts:
        response = teacher.post(url, body, format='json')
        assert 400 <= response.status_code < 500, (body, response.status_code)
    assert not BatchLessonItem.objects.filter(batch=batch).exists()

    # Legacy generic routes (MAP-178) and @planned routes (MAP-203): gone for every role.
    lesson = Lesson.objects.filter(student=student_user).first()
    invoice = Invoice.objects.create(
        invoice_type='teacher_payment', teacher=teacher_user, school=school, status='pending',
        payment_balance=Decimal('1.00'), total_amount=Decimal('1.00'),
    )
    legacy_paths = [
        '/api/billing/teachers/', '/api/billing/students/', '/api/billing/lessons/',
        f'/api/billing/teachers/{teacher_user.id}/', f'/api/billing/students/{student_user.id}/',
        f'/api/billing/lessons/{lesson.id}/', f'/api/billing/invoices/{invoice.id}/',
        '/api/billing/teachers/all/', f'/api/billing/teachers/{teacher_user.id}/approve/',
        '/api/billing/lessons/request/', f'/api/billing/lessons/{lesson.id}/confirm/',
        f'/api/billing/lessons/{lesson.id}/complete/', '/api/billing/invoices/teacher/',
        f'/api/billing/invoices/teacher/{invoice.id}/approve/',
    ]
    for user in (None, student_user, teacher_user, management_user):
        client = _client(user)
        for path in legacy_paths:
            assert client.get(path).status_code == 404, (user, path)

    teacher.put(f'/api/billing/invoices/{invoice.id}/', {'status': 'paid'}, format='json')
    invoice.refresh_from_db()
    assert invoice.status == 'pending'


# ---------------------------------------------------------------------------
# Finding #3 — MAP-180
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_finding_03_concurrent_webhook_credits_once(school, student_user):
    """Audit 2026-09-07 finding #3 (fix: MAP-180): two concurrent deliveries of one payment credit the wallet once."""
    amount = Decimal('60.00')
    invoice = _sent_invoice(student_user, 'INV-AUDIT-3', amount)
    account = _account(student_user)
    event = _enriched_event('tx-audit-3', 'INV-AUDIT-3', amount)
    balance_before = account.balance

    def deliver():
        process_webhook_event(HelcimWebhookEvent.objects.get(pk=event.pk))

    _race(deliver)

    assert CreditTransaction.objects.filter(account=account).count() == 1
    event.refresh_from_db()
    account.refresh_from_db()
    assert account.balance - balance_before == event.amount - event.fee_amount
    assert account.balance - balance_before == CreditTransaction.objects.get(account=account).amount
    assert PreBillingInvoice.objects.get(pk=invoice.pk).status == 'paid'


# ---------------------------------------------------------------------------
# Finding #4 — MAP-196 (open, P3)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason='MAP-196 multi-school settlement')
@pytest.mark.django_db
def test_finding_04_invoice_number_collision_never_credits_other_school(school, second_school, student_user):
    """Audit 2026-09-07 finding #4 (fix: MAP-196): a payment verified for one school never credits another school's invoice that shares its Helcim invoice number."""
    amount = Decimal('60.00')
    other_student = _student(second_school, 'collision@audit.test')
    own_invoice = _sent_invoice(student_user, 'INV-SHARED', amount)
    other_invoice = _sent_invoice(other_student, 'INV-SHARED', amount)  # newer row, same number
    own_account, other_account = _account(student_user), _account(other_student)
    event = _enriched_event('tx-audit-4', 'INV-SHARED', amount, school=school)

    process_webhook_event(event)

    own_account.refresh_from_db()
    other_account.refresh_from_db()
    assert other_account.balance == Decimal('0.00')
    assert not CreditTransaction.objects.filter(account=other_account).exists()
    assert PreBillingInvoice.objects.get(pk=other_invoice.pk).status == 'sent'
    assert own_account.balance == amount
    assert PreBillingInvoice.objects.get(pk=own_invoice.pk).status == 'paid'


# ---------------------------------------------------------------------------
# Finding #5 — MAP-184
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_finding_05_adjustment_keeps_credit_and_last_lesson_makes_no_provider_call(
    school, school_settings, teacher_user, management_user,
):
    """Audit 2026-09-07 finding #5 (fix: MAP-184): removing a lesson keeps the wallet credit already applied, and removing the last lesson is refused before any Helcim call."""
    manager = _client(management_user)
    helcim = mock.Mock()
    helcim.create_invoice.return_value = {'invoiceId': 'inv_audit_5', 'token': 'tok_audit_5', 'invoiceNumber': 'MK-AUDIT-5'}
    helcim.cancel_invoice.return_value = {}
    helcim.get_invoice_by_number.return_value = None

    def remove(invoice, lesson):
        with mock.patch('billing.views.pre_billing.HelcimClient', return_value=helcim), \
             mock.patch('billing.services.email_service.PreBillingEmailService.send_payment_request',
                        return_value=(True, 'sent')):
            return manager.post(
                reverse('management_pre_billing_remove_lesson', kwargs={'invoice_id': invoice.id}),
                {'lesson_id': lesson.id}, format='json',
            )

    # (a) Credit partially covered a two-lesson invoice; one lesson is removed.
    student = _student(school, 'adjust@audit.test')
    _contact(student, customer_id='cust_audit_5a')
    removed, kept = _billable_lessons(student, teacher_user, 2)
    original_gross = _charge(removed) + _charge(kept)
    applied_credit = _charge(kept) + _charge(removed) / 2
    wallet = _account(student, balance=applied_credit)
    invoice = _sent_invoice(student, 'INV-AUDIT-5A', original_gross - applied_credit)
    invoice.helcim_invoice_id = 'inv_old_5a'
    invoice.save(update_fields=['helcim_invoice_id'])
    invoice.lessons.add(removed, kept)

    response = remove(invoice, removed)

    assert response.status_code == 200, response.data
    new_gross = _charge(kept)
    original_credit = original_gross - (original_gross - applied_credit)
    invoice.refresh_from_db()
    assert invoice.amount == new_gross - min(original_credit, new_gross)
    wallet.refresh_from_db()
    assert wallet.balance == applied_credit  # the adjustment never touches the wallet

    # (b) Removing the only lesson: 400, and Helcim is never called.
    helcim.reset_mock()
    student_b = _student(school, 'lastlesson@audit.test')
    _contact(student_b, customer_id='cust_audit_5b')
    (only,) = _billable_lessons(student_b, teacher_user, 1)
    last = _sent_invoice(student_b, 'INV-AUDIT-5B', _charge(only))
    last.helcim_invoice_id = 'inv_old_5b'
    last.save(update_fields=['helcim_invoice_id'])
    last.lessons.add(only)

    response = remove(last, only)

    assert response.status_code == 400
    helcim.create_invoice.assert_not_called()
    helcim.cancel_invoice.assert_not_called()
    last.refresh_from_db()
    assert last.status == 'sent'
    assert last.helcim_invoice_id == 'inv_old_5b'


# ---------------------------------------------------------------------------
# Finding #6 — MAP-185
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_finding_06_send_timeout_and_crash_leave_one_provider_invoice(school, teacher_user, management_user):
    """Audit 2026-09-07 finding #6 (fix: MAP-185): a send that timed out after Helcim accepted it, or crashed before saving, ends sent with exactly one Helcim invoice — never a duplicate, never stranded."""
    timeout_customer, crash_customer = 'cust_audit_timeout', 'cust_audit_crash'
    invoices = {}
    for customer in (timeout_customer, crash_customer):
        student = _student(school, f'{customer}@audit.test')
        _contact(student, customer_id=customer)
        (lesson,) = _billable_lessons(student, teacher_user, 1)
        invoice = PreBillingInvoice.objects.create(
            student=student, school=school, status='draft', amount=_charge(lesson),
            period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
        )
        invoice.lessons.add(lesson)
        invoices[customer] = invoice

    # Helcim's side: every create it accepts, by number. Lookups answer from it.
    provider = {}

    def create_invoice(**kwargs):
        customer = kwargs.get('customer_id')
        first_for_customer = not any(r['customer'] == customer for r in provider.values())
        number = kwargs.get('invoice_number') or f'H{len(provider) + 1}'
        invoice_id = 8000 + len(provider) + 1
        provider[number] = {'customer': customer, 'invoiceId': invoice_id,
                            'invoiceNumber': number, 'token': f'tok_{invoice_id}'}
        if first_for_customer and customer == timeout_customer:
            raise HelcimAPIError('timeout after Helcim accepted', status_code=None)
        if first_for_customer and customer == crash_customer:
            return {'invoiceId': invoice_id, 'invoiceNumber': number}  # our side fails before persisting
        return provider[number]

    helcim = mock.Mock()
    helcim.create_invoice.side_effect = create_invoice
    helcim.get_invoice_by_number.side_effect = provider.get

    def run_for(pending):
        run = InvoiceSendRun.objects.create(
            school=school, period_start=date(2026, 6, 1), created_by=management_user, item_count=len(pending),
        )
        for position, invoice in enumerate(pending):
            InvoiceSendItem.objects.create(run=run, invoice=invoice, position=position)
        with mock.patch('billing.services.invoice_sending.HelcimClient', return_value=helcim), \
             mock.patch('billing.services.invoice_sending.PreBillingEmailService.send_payment_request',
                        return_value=(True, 'sent')):
            call_command('process_invoice_send_runs', '--once', stdout=StringIO())
        return run

    run_for(list(invoices.values()))
    # The crashed send is left for a later run to recover — never back in draft.
    crashed = PreBillingInvoice.objects.get(pk=invoices[crash_customer].pk)
    assert crashed.status != 'draft'
    second_run = run_for([crashed])

    assert set(second_run.items.values_list('status', flat=True)) == {'sent'}
    for customer, invoice in invoices.items():
        created = [r for r in provider.values() if r['customer'] == customer]
        assert len(created) == 1, (customer, created)
        invoice.refresh_from_db()
        assert invoice.status == 'sent'
        assert invoice.helcim_invoice_id == str(created[0]['invoiceId'])


# ---------------------------------------------------------------------------
# Finding #7 — MAP-183
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_finding_07_concurrent_payroll_generate_one_invoice_and_paid_keeps_total(
    management_user, teacher_user, student_user, school, school_settings,
):
    """Audit 2026-09-07 finding #7 (fix: MAP-183): two concurrent payroll generates yield one invoice, and a status change never alters its total."""
    _contact(student_user)
    batch = MonthlyInvoiceBatch.objects.create(teacher=teacher_user, school=school, month=6, year=2026, status='submitted')
    _batch_item(batch, student_user, school_settings)
    manager = _client(management_user)
    assert manager.post(reverse('management_approve_batch', kwargs={'batch_id': batch.id})).status_code == 200

    url = reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id})
    user_id = management_user.id

    def generate():
        return _client(User.objects.get(pk=user_id)).post(url, format='json').status_code

    statuses = sorted(_race(generate))

    assert statuses == [200, 409], statuses
    invoice = Invoice.objects.get(teacher=teacher_user, invoice_type='teacher_payment')
    total_before = invoice.total_amount
    assert total_before > Decimal('0.00')

    response = manager.patch(
        reverse('management_patch_invoice', kwargs={'pk': invoice.pk}),
        {'status': 'paid', 'date_paid': '2026-07-05'}, format='json',
    )
    assert response.status_code == 200
    invoice.refresh_from_db()
    assert invoice.status == 'paid'
    assert invoice.total_amount == total_before

    invoice.status = 'approved'
    invoice.save()
    invoice.refresh_from_db()
    assert invoice.total_amount == total_before


# ---------------------------------------------------------------------------
# Finding #8 — MAP-154
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_finding_08_enrichment_failed_recovered_by_scheduler_tick(school, student_user):
    """Audit 2026-09-07 finding #8 (fix: MAP-154): a payment stuck in enrichment_failed is credited by the next unattended scheduler tick."""
    amount = Decimal('60.00')
    invoice = _sent_invoice(student_user, 'INV-AUDIT-8', amount)
    account = _account(student_user)
    event = HelcimWebhookEvent.objects.create(
        helcim_transaction_id='tx-audit-8', raw_payload={'id': 'tx-audit-8', 'type': 'cardTransaction'},
        invoice_id='', amount=Decimal('0.00'), processing_status='enrichment_failed',
    )
    transaction = {'invoiceNumber': 'INV-AUDIT-8', 'amount': str(amount), 'status': 'APPROVED', 'type': 'purchase'}

    with mock.patch('billing.services.helcim_client.HelcimClient.get_card_transaction', return_value=transaction), \
         mock.patch('billing.services.helcim_client.HelcimClient.list_card_transactions', return_value=[]), \
         mock.patch('billing.management.commands.run_scheduler.start_http_server'):
        call_command('run_scheduler', '--once', stdout=StringIO())

    event.refresh_from_db()
    account.refresh_from_db()
    assert event.processing_status == 'credited'
    assert account.balance == event.amount - event.fee_amount
    assert PreBillingInvoice.objects.get(pk=invoice.pk).status == 'paid'


# ---------------------------------------------------------------------------
# Finding #9 — MAP-186
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_finding_09_ledger_explains_balance_and_sent_invoice_is_snapshot(
    management_user, teacher_user, student_user, school, school_settings,
):
    """Audit 2026-09-07 finding #9 (fix: MAP-186): every balance change is explained by the ledger, and a sent invoice does not change when the schedule behind it does."""
    manager = _client(management_user)

    # (a) payment webhook → batch approval (one lesson covered, one short) → payroll generate.
    _contact(student_user)
    batch = MonthlyInvoiceBatch.objects.create(teacher=teacher_user, school=school, month=6, year=2026, status='submitted')
    completed = _batch_item(batch, student_user, school_settings, status='completed', day=8)
    _batch_item(batch, student_user, school_settings, status='forfeited', day=15)
    account = _account(student_user)
    payment = completed.student_rate * completed.duration
    _sent_invoice(student_user, 'INV-AUDIT-9', payment)
    process_webhook_event(_enriched_event('tx-audit-9', 'INV-AUDIT-9', payment))
    account.refresh_from_db()
    assert account.balance > Decimal('0.00')  # the payment landed

    assert manager.post(reverse('management_approve_batch', kwargs={'batch_id': batch.id})).status_code == 200
    generate = manager.post(reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id}), format='json')
    assert generate.status_code == 200, generate.data

    account.refresh_from_db()
    assert account.balance == _ledger_sum(account)

    # (b) a schedule-projected invoice, sent, then its schedule changes.
    student = _student(school, 'snapshot@audit.test')
    _contact(student, customer_id='cust_audit_9')
    today = date.today()
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    schedule = RecurringLessonsSchedule.objects.create(
        teacher=teacher_user, student=student, school=school, day_of_week=2, start_time=time(15, 0),
        duration=Decimal('1.0'), lesson_type='online', teacher_rate=school_settings.online_teacher_rate,
        student_rate=school_settings.online_student_rate, is_active=True, start_date=date(year, month, 1),
    )
    assert manager.post(reverse('management_pre_billing_generate'), {'month': month, 'year': year}, format='json').status_code == 200
    invoice = PreBillingInvoice.objects.get(student=student, period_start=date(year, month, 1))

    helcim = mock.Mock()
    helcim.create_invoice.return_value = {'invoiceId': 'inv_audit_9', 'token': 'tok_audit_9', 'invoiceNumber': 'MK-AUDIT-9'}
    helcim.get_invoice_by_number.return_value = None
    with mock.patch('billing.services.invoice_sending.HelcimClient', return_value=helcim), \
         mock.patch('billing.services.invoice_sending.PreBillingEmailService.send_payment_request',
                    return_value=(True, 'sent')):
        sent = manager.post(reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id}), format='json')
    assert sent.status_code == 200, sent.data

    detail_url = reverse('management_pre_billing_detail', kwargs={'invoice_id': invoice.id})
    issued = manager.get(detail_url).data

    schedule.student_rate = schedule.student_rate + school_settings.online_student_rate
    schedule.day_of_week = (schedule.day_of_week + 1) % 7
    schedule.save(update_fields=['student_rate', 'day_of_week'])

    after = manager.get(detail_url).data
    assert after['amount'] == issued['amount']
    assert after['lessons'] == issued['lessons']
