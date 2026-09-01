"""
Unit tests for pre-billing send hardening:

  - Wallet credit rides as a Helcim invoice-level discount so the hosted
    payment page charges exactly invoice.amount (net), never gross
  - Double-send guard: concurrent/second send returns 409, no duplicate
    Helcim invoice
  - Helcim failure releases the 'sending' claim back to draft
  - Email failure is recorded on the invoice (email_sent/email_error)
    and recoverable via the resend-email endpoint
"""

from datetime import date
from decimal import Decimal
from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from datetime import time

from billing.models import (
    PreBillingInvoice,
    BillableContact,
    Lesson,
    StudentCreditAccount,
    RecurringLessonsSchedule,
)
from billing.services.helcim_client import HelcimAPIError

HELCIM_RESPONSE = {'invoiceId': 111, 'invoiceNumber': 'INV900', 'token': 'tok-abc'}


@pytest.fixture
def management_client(management_user):
    client = APIClient()
    client.force_authenticate(user=management_user)
    return client


def _student_with_contact(school, tag='send'):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    student = User.objects.create_user(
        email=f'student_{tag}@prebilling.test',
        password='testpass123',
        user_type='student',
        first_name='Send',
        last_name='Hardening',
        school=school,
        is_approved=True,
    )
    BillableContact.objects.create(
        student=student,
        school=school,
        is_primary=True,
        first_name='Parent',
        last_name='Hardening',
        email=f'contact_{tag}@prebilling.test',
        phone='555-0100',
        street_address='123 Test St',
        city='Toronto',
        province='ON',
        postal_code='M5H 2N2',
        helcim_customer_id='cust-1',
    )
    return student


def _sendable_invoice(school, teacher_user, student, amount, lesson_prices=('60.00', '60.00')):
    """Invoice with real lessons; amount may be below gross (credit applied)."""
    invoice = PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='draft',
        amount=Decimal(amount),
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
    )
    for i, price in enumerate(lesson_prices):
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student,
            school=school,
            lesson_type='online',
            teacher_rate=Decimal('45.00'),
            student_rate=Decimal(price),
            scheduled_date=date(2026, 8, 3 + 7 * i),
            duration=1.0,
            status='confirmed',
        )
        # Lesson.save() auto-marks a student's first lesson as trial and zeroes
        # student_rate — bypass via queryset update to keep sentinel rates.
        Lesson.objects.filter(pk=lesson.pk).update(
            is_trial=False, student_rate=Decimal(price)
        )
        invoice.lessons.add(lesson)
    return invoice


@pytest.mark.django_db
def test_send_passes_credit_as_helcim_discount(management_client, school, teacher_user):
    """gross 120, amount 75 → Helcim invoice gets discount 45 so amountDue == 75."""
    student = _student_with_contact(school, 'discount')
    invoice = _sendable_invoice(school, teacher_user, student, '75.00')

    with mock.patch('billing.services.invoice_sending.HelcimClient') as MockClient:
        MockClient.return_value.create_invoice.return_value = HELCIM_RESPONSE
        response = management_client.post(
            reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        )

    assert response.status_code == 200
    _, kwargs = MockClient.return_value.create_invoice.call_args
    assert kwargs['discount'] == {'amount': 45.0, 'details': 'Account credit applied'}
    invoice.refresh_from_db()
    assert invoice.status == 'sent'


@pytest.mark.django_db
def test_send_without_credit_passes_no_discount(management_client, school, teacher_user):
    """amount == gross → discount is None."""
    student = _student_with_contact(school, 'nodiscount')
    invoice = _sendable_invoice(school, teacher_user, student, '120.00')

    with mock.patch('billing.services.invoice_sending.HelcimClient') as MockClient:
        MockClient.return_value.create_invoice.return_value = HELCIM_RESPONSE
        response = management_client.post(
            reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        )

    assert response.status_code == 200
    _, kwargs = MockClient.return_value.create_invoice.call_args
    assert kwargs['discount'] is None


@pytest.mark.django_db
def test_second_send_returns_409_no_duplicate_helcim_invoice(
    management_client, school, teacher_user
):
    """Second send of the same invoice → 409, create_invoice called exactly once."""
    student = _student_with_contact(school, 'conflict')
    invoice = _sendable_invoice(school, teacher_user, student, '120.00')
    url = reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})

    with mock.patch('billing.services.invoice_sending.HelcimClient') as MockClient:
        MockClient.return_value.create_invoice.return_value = HELCIM_RESPONSE
        r1 = management_client.post(url)
        r2 = management_client.post(url)

    assert r1.status_code == 200
    # Second attempt fails the draft-status guard (400) — and even a request
    # racing past that guard hits the atomic claim (409). Either way: no call.
    assert r2.status_code in (400, 409)
    assert MockClient.return_value.create_invoice.call_count == 1


@pytest.mark.django_db
def test_helcim_failure_releases_claim_back_to_draft(management_client, school, teacher_user):
    """create_invoice raises → invoice back to draft (not stuck in 'sending')."""
    student = _student_with_contact(school, 'release')
    invoice = _sendable_invoice(school, teacher_user, student, '120.00')

    with mock.patch('billing.services.invoice_sending.HelcimClient') as MockClient:
        MockClient.return_value.create_invoice.side_effect = HelcimAPIError('boom', status_code=500)
        response = management_client.post(
            reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        )

    assert response.status_code == 400
    invoice.refresh_from_db()
    assert invoice.status == 'draft'


@pytest.mark.django_db
def test_email_failure_recorded_and_recoverable_via_resend(
    management_client, school, teacher_user
):
    """Email fails after Helcim send → email_sent=False + error stored; resend recovers."""
    student = _student_with_contact(school, 'emailfail')
    invoice = _sendable_invoice(school, teacher_user, student, '120.00')

    with mock.patch('billing.services.invoice_sending.HelcimClient') as MockClient, \
         mock.patch(
             'billing.services.invoice_sending.PreBillingEmailService.send_payment_request',
             return_value=(False, 'Failed to send email: Resend down'),
         ):
        MockClient.return_value.create_invoice.return_value = HELCIM_RESPONSE
        response = management_client.post(
            reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        )

    assert response.status_code == 200  # Helcim invoice exists — send succeeded
    invoice.refresh_from_db()
    assert invoice.status == 'sent'
    assert invoice.email_sent is False
    assert 'Resend down' in invoice.email_error

    with mock.patch(
        'billing.services.invoice_sending.PreBillingEmailService.send_payment_request',
        return_value=(True, 'Email sent successfully'),
    ) as mock_send:
        response = management_client.post(
            reverse('management_pre_billing_resend_email', kwargs={'invoice_id': invoice.id})
        )

    assert response.status_code == 200
    invoice.refresh_from_db()
    assert invoice.email_sent is True
    assert invoice.email_error == ''
    # Resend reuses the stored payment token — same hosted-payment URL
    assert 'tok-abc' in mock_send.call_args[0][6]


@pytest.mark.django_db
def test_resend_email_rejects_draft_invoice(management_client, school, teacher_user):
    """Draft invoices have no payment link — resend must 400."""
    student = _student_with_contact(school, 'resenddraft')
    invoice = _sendable_invoice(school, teacher_user, student, '120.00')

    response = management_client.post(
        reverse('management_pre_billing_resend_email', kwargs={'invoice_id': invoice.id})
    )
    assert response.status_code == 400


def _projected_invoice(school, teacher_user, student, amount='0.00'):
    """Bill-ahead invoice: empty lessons M2M + an active weekly schedule."""
    RecurringLessonsSchedule.objects.create(
        teacher=teacher_user,
        student=student,
        school=school,
        day_of_week=0,  # Mondays
        start_time=time(15, 0),
        duration=Decimal('1.00'),
        lesson_type='online',
        teacher_rate=Decimal('45.00'),
        student_rate=Decimal('60.00'),
        is_active=True,
        start_date=date(2020, 1, 1),
    )
    return PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='draft',
        amount=Decimal(amount),
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
    )


@pytest.mark.django_db
def test_projected_invoice_sends_with_schedule_line_items(management_client, school, teacher_user):
    """
    Bill-ahead invoices have an empty M2M — send must project line items from
    the recurring schedule instead of rejecting with 'no lesson dates'.
    October 2026 has 4 Mondays → 4 line items × $60, amount recomputed to 240.
    """
    student = _student_with_contact(school, 'projected')
    invoice = _projected_invoice(school, teacher_user, student, '0.00')  # stale amount

    with mock.patch('billing.services.invoice_sending.HelcimClient') as MockClient:
        MockClient.return_value.create_invoice.return_value = HELCIM_RESPONSE
        response = management_client.post(
            reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        )

    assert response.status_code == 200
    _, kwargs = MockClient.return_value.create_invoice.call_args
    line_items = kwargs['line_items']
    assert len(line_items) == 4  # Mondays in Oct 2026: 5, 12, 19, 26
    assert all(li['price'] == 60.0 for li in line_items)
    assert all(li['sku'].startswith('LESSON-P') for li in line_items)
    invoice.refresh_from_db()
    assert invoice.status == 'sent'
    assert invoice.amount == Decimal('240.00')  # recomputed from projection


@pytest.mark.django_db
def test_projected_invoice_send_applies_current_credit(management_client, school, teacher_user):
    """Recompute at send uses live credit: gross 240 − 45 credit → amount 195, discount 45."""
    student = _student_with_contact(school, 'projcredit')
    invoice = _projected_invoice(school, teacher_user, student, '240.00')
    StudentCreditAccount.objects.create(
        student=student, school=school, balance=Decimal('45.00')
    )

    with mock.patch('billing.services.invoice_sending.HelcimClient') as MockClient:
        MockClient.return_value.create_invoice.return_value = HELCIM_RESPONSE
        response = management_client.post(
            reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        )

    assert response.status_code == 200
    _, kwargs = MockClient.return_value.create_invoice.call_args
    assert kwargs['discount'] == {'amount': 45.0, 'details': 'Account credit applied'}
    invoice.refresh_from_db()
    assert invoice.amount == Decimal('195.00')


@pytest.mark.django_db
def test_projected_invoice_detail_lists_projected_dates(management_client, school, teacher_user):
    """Detail endpoint shows the projected schedule dates, flagged is_projected."""
    student = _student_with_contact(school, 'projdetail')
    invoice = _projected_invoice(school, teacher_user, student, '240.00')

    response = management_client.get(
        reverse('management_pre_billing_detail', kwargs={'invoice_id': invoice.id})
    )
    assert response.status_code == 200
    assert response.data['is_projected'] is True
    dates = [l['scheduled_date'] for l in response.data['lessons']]
    assert dates == ['2026-10-05', '2026-10-12', '2026-10-19', '2026-10-26']
    assert all(l['id'] < 0 for l in response.data['lessons'])


@pytest.mark.django_db
def test_skip_date_recomputes_amount_and_send_omits_it(management_client, school, teacher_user):
    """
    Skipping a projected date drops it from amount, line items, and restores
    cleanly. Oct 2026 Mondays: 5, 12, 19, 26 @ $60 → gross 240.
    """
    student = _student_with_contact(school, 'skipdate')
    invoice = _projected_invoice(school, teacher_user, student, '240.00')
    skip_url = reverse('management_pre_billing_skip_date', kwargs={'invoice_id': invoice.id})

    # Skip Oct 12 → amount 180, date listed in excluded_dates
    response = management_client.post(skip_url, {'date': '2026-10-12'}, format='json')
    assert response.status_code == 200
    assert response.data['amount'] == '180.00'
    assert response.data['excluded_dates'] == ['2026-10-12']
    dates = [l['scheduled_date'] for l in response.data['lessons']]
    assert '2026-10-12' not in dates and len(dates) == 3

    # Send: line items must omit the skipped date
    with mock.patch('billing.services.invoice_sending.HelcimClient') as MockClient:
        MockClient.return_value.create_invoice.return_value = HELCIM_RESPONSE
        send = management_client.post(
            reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        )
    assert send.status_code == 200
    _, kwargs = MockClient.return_value.create_invoice.call_args
    assert len(kwargs['line_items']) == 3
    assert all('2026-10-12' not in li['description'] for li in kwargs['line_items'])
    invoice.refresh_from_db()
    assert invoice.amount == Decimal('180.00')


@pytest.mark.django_db
def test_restore_date_and_guards(management_client, school, teacher_user):
    """Restore brings the date back; guards reject bad dates and non-drafts."""
    student = _student_with_contact(school, 'restoredate')
    invoice = _projected_invoice(school, teacher_user, student, '240.00')
    skip_url = reverse('management_pre_billing_skip_date', kwargs={'invoice_id': invoice.id})
    restore_url = reverse('management_pre_billing_restore_date', kwargs={'invoice_id': invoice.id})

    # Not a projected date → 400
    assert management_client.post(
        skip_url, {'date': '2026-10-06'}, format='json'
    ).status_code == 400
    # Garbage date → 400
    assert management_client.post(
        skip_url, {'date': 'next tuesday'}, format='json'
    ).status_code == 400

    management_client.post(skip_url, {'date': '2026-10-05'}, format='json')
    response = management_client.post(restore_url, {'date': '2026-10-05'}, format='json')
    assert response.status_code == 200
    assert response.data['excluded_dates'] == []
    assert response.data['amount'] == '240.00'

    # Restoring a date that isn't skipped → 400
    assert management_client.post(
        restore_url, {'date': '2026-10-05'}, format='json'
    ).status_code == 400

    # Non-draft guard
    PreBillingInvoice.objects.filter(pk=invoice.pk).update(status='sent')
    assert management_client.post(
        skip_url, {'date': '2026-10-05'}, format='json'
    ).status_code == 400


@pytest.mark.django_db
def test_generate_refresh_preserves_skipped_dates(management_client, school, teacher_user):
    """Re-running Generate must not resurrect a skipped date's amount."""
    student = _student_with_contact(school, 'skiprefresh')
    invoice = _projected_invoice(school, teacher_user, student, '240.00')
    management_client.post(
        reverse('management_pre_billing_skip_date', kwargs={'invoice_id': invoice.id}),
        {'date': '2026-10-12'}, format='json',
    )

    response = management_client.post(
        reverse('management_pre_billing_generate'),
        {'month': 10, 'year': 2026}, format='json',
    )
    assert response.status_code == 200
    invoice.refresh_from_db()
    assert invoice.amount == Decimal('180.00')
    assert invoice.excluded_dates == ['2026-10-12']


@pytest.mark.django_db
def test_no_lessons_and_no_schedule_still_rejected(management_client, school, teacher_user):
    """Empty M2M and no active schedule → clear 'no lesson dates' error."""
    student = _student_with_contact(school, 'projempty')
    invoice = PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='draft',
        amount=Decimal('100.00'),
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
    )

    response = management_client.post(
        reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
    )
    assert response.status_code == 400
    assert 'no lesson dates' in response.data['error']
    invoice.refresh_from_db()
    assert invoice.status == 'draft'


@pytest.mark.django_db
def test_serializer_exposes_payment_url_and_email_state(management_client, school, teacher_user):
    """Detail endpoint returns payment_url built from the stored token."""
    student = _student_with_contact(school, 'serialize')
    invoice = _sendable_invoice(school, teacher_user, student, '120.00')

    with mock.patch('billing.services.invoice_sending.HelcimClient') as MockClient:
        MockClient.return_value.create_invoice.return_value = HELCIM_RESPONSE
        management_client.post(
            reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        )

    response = management_client.get(
        reverse('management_pre_billing_detail', kwargs={'invoice_id': invoice.id})
    )
    assert response.status_code == 200
    assert response.data['payment_url'].endswith('/order/?token=tok-abc')
    assert 'email_sent' in response.data
    assert 'email_error' in response.data
