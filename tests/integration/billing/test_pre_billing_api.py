"""
Wave 0 RED stubs — turns green when Plans 02-04 land the model, endpoints, and URLs.

Integration test stubs for Pre-Billing Invoice API endpoints.
Covers BILL-03 (generate), BILL-05 (send), BILL-07 (send-all),
BILL-08 (remove-lesson), BILL-09 (void failure).

Tests FAIL at collection time (ImportError: PreBillingInvoice does not exist)
— expected RED state until Plan 02 ships the model.

Mocked Helcim HTTP patterns follow test_helcim_client.py approach
(patch billing.services.helcim_client.requests).
"""

import pytest
from decimal import Decimal
from datetime import date, time
from unittest.mock import patch, Mock

from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

from billing.models import PreBillingInvoice, BillableContact, Lesson
from billing.services.helcim_client import HelcimAPIError

User = get_user_model()


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def management_client(management_user):
    """Authenticated APIClient for the primary school's management user."""
    client = APIClient()
    client.force_authenticate(user=management_user)
    return client


@pytest.fixture
def student_with_contact(school, teacher_user, db):
    """Active student with a primary BillableContact — ready for billing."""
    student = User.objects.create_user(
        email="billing_student@prebilling.test",
        password="testpass123",
        user_type="student",
        first_name="Billing",
        last_name="Student",
        school=school,
        is_approved=True,
    )
    contact = BillableContact.objects.create(
        student=student,
        school=school,
        is_primary=True,
        first_name="Billing",
        last_name="Contact",
        email="billing_contact@prebilling.test",
        phone="555-0200",
        street_address="123 Test St",
        city="Toronto",
        province="ON",
        postal_code="M5H 2N2",
    )
    return student, contact


def _make_confirmed_lesson(student, teacher, school, lesson_date=None):
    """Create a confirmed Lesson for billing draft generation."""
    from django.utils import timezone
    return Lesson.objects.create(
        teacher=teacher,
        student=student,
        school=school,
        lesson_type='online',
        teacher_rate=Decimal('45.00'),
        student_rate=Decimal('60.00'),
        scheduled_date=lesson_date or date(2026, 6, 10),
        duration=1.0,
        status='confirmed',
    )


def _make_draft_invoice(student, school, amount=Decimal('120.00')):
    """Create a draft PreBillingInvoice for testing send/void endpoints."""
    return PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='draft',
        amount=amount,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )


# ---------------------------------------------------------------------------
# Helcim HTTP mock helpers
# ---------------------------------------------------------------------------

def _helcim_create_invoice_ok():
    """Mock for successful Helcim create_invoice call."""
    return Mock(
        ok=True,
        status_code=200,
        json=lambda: {'invoiceId': 'inv_test_123', 'token': 'tok_test_abc', 'invoiceNumber': '001'},
        text='',
    )


def _helcim_create_customer_ok():
    """Mock for successful Helcim create_customer call."""
    return Mock(
        ok=True,
        status_code=200,
        json=lambda: {'id': 99001},
        text='',
    )


def _helcim_cancel_invoice_ok():
    """Mock for successful Helcim cancel_invoice call."""
    return Mock(
        ok=True,
        status_code=200,
        json=lambda: {},
        text='',
    )


def _helcim_cancel_invoice_fail():
    """Mock for failed Helcim cancel_invoice (settled invoice)."""
    return Mock(
        ok=False,
        status_code=400,
        text='settled invoice',
        json=lambda: {'error': 'settled invoice'},
    )


# ---------------------------------------------------------------------------
# Tests — generate drafts (BILL-03)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_generate_drafts(management_client, school, teacher_user, student_with_contact):
    """
    POST generate endpoint returns 200 with generated/skipped_existing/skipped_no_contact.
    BILL-03: draft generation creates PreBillingInvoice per student with BillableContact.
    """
    # Target the CURRENT month explicitly so the confirmed-Lesson sourcing path is
    # exercised. Generate now defaults to NEXT month (Phase 24 D-03/D-07), which would
    # source from RecurringLessonsSchedule instead.
    today = date.today()
    student, contact = student_with_contact
    _make_confirmed_lesson(
        student, teacher_user, school, lesson_date=date(today.year, today.month, 10)
    )

    # Student without contact — must be skipped
    User.objects.create_user(
        email="no_contact@prebilling.test",
        password="pass",
        user_type="student",
        first_name="No",
        last_name="Contact",
        school=school,
        is_approved=True,
    )

    url = reverse('management_pre_billing_generate')
    response = management_client.post(
        url, {'month': today.month, 'year': today.year}, format='json'
    )

    assert response.status_code == 200
    assert response.data['generated'] >= 1
    assert response.data['skipped_no_contact'] >= 1
    assert 'skipped_existing' in response.data
    assert 'skipped_no_schedule' in response.data  # Phase 24 D-09
    assert PreBillingInvoice.objects.filter(school=school).count() >= 1


@pytest.mark.django_db
def test_generate_drafts_incremental(management_client, school, teacher_user, student_with_contact):
    """
    POST generate is idempotent and incremental — students with an existing invoice
    for the current period are skipped; new students get a fresh draft.
    BILL-03: no duplicate drafts; skipped_existing count reflects pre-existing invoices.
    """
    student, contact = student_with_contact

    today = date.today()
    period_start = today.replace(day=1)
    import calendar
    last_day = calendar.monthrange(today.year, today.month)[1]
    period_end = today.replace(day=last_day)

    # Pre-create a draft for the existing student
    PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='draft',
        amount=Decimal('120.00'),
        period_start=period_start,
        period_end=period_end,
    )

    # Target the SAME period the pre-created draft lives in (current month). Generate
    # now defaults to next month (Phase 24 D-03/D-07), so the period must be explicit.
    url = reverse('management_pre_billing_generate')
    response = management_client.post(
        url, {'month': today.month, 'year': today.year}, format='json'
    )

    assert response.status_code == 200
    # Phase 24 D-10: a pre-existing DRAFT in the targeted period is refreshed, not
    # skipped — so it is NOT counted in skipped_existing (only sent/adjusted are).
    # The student must still have exactly one invoice (no duplicate created).
    assert PreBillingInvoice.objects.filter(school=school, student=student).count() == 1


@pytest.mark.django_db
def test_duplicate_prebilling_invoice_blocked_by_constraint(school, student_with_contact):
    """
    Bug 8 / duplicate protection: the DB constraint
    unique_prebilling_per_student_period prevents two invoices for the same
    student+school+period, even if a concurrent generate slips past the app-level
    existence check.
    """
    from django.db import IntegrityError, transaction
    student, _ = student_with_contact
    period_start = date(2026, 1, 1)
    period_end = date(2026, 1, 31)

    PreBillingInvoice.objects.create(
        student=student, school=school, status='draft', amount=Decimal('100.00'),
        period_start=period_start, period_end=period_end,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PreBillingInvoice.objects.create(
                student=student, school=school, status='draft', amount=Decimal('100.00'),
                period_start=period_start, period_end=period_end,
            )


# ---------------------------------------------------------------------------
# Tests — send invoice (BILL-05, BILL-07)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_invoice(management_client, school, teacher_user, student_with_contact):
    """
    POST send endpoint creates Helcim customer (lazy), creates invoice, transitions to sent.
    BILL-05: contact.helcim_customer_id stored; BILL-07: helcim_invoice_id + payment_token saved.
    """
    student, contact = student_with_contact
    invoice = _make_draft_invoice(student, school)
    lesson = _make_confirmed_lesson(student, teacher_user, school)
    invoice.lessons.add(lesson)

    with patch('billing.services.helcim_client.requests.post') as mock_post, \
         patch('billing.services.email_service.PreBillingEmailService.send_payment_request') as mock_email:
        # First call: create_customer; second call: create_invoice
        mock_post.side_effect = [_helcim_create_customer_ok(), _helcim_create_invoice_ok()]
        mock_email.return_value = (True, 'sent')

        url = reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        response = management_client.post(url, format='json')

    assert response.status_code == 200

    contact.refresh_from_db()
    invoice.refresh_from_db()
    assert contact.helcim_customer_id == str(99001)
    assert invoice.status == 'sent'
    assert invoice.helcim_invoice_id == 'inv_test_123'
    assert invoice.payment_token == 'tok_test_abc'


@pytest.mark.django_db
def test_send_sets_status(management_client, school, teacher_user, student_with_contact):
    """
    POST send transitions invoice status from draft to sent.
    BILL-07: status field must be 'sent' after successful send.
    """
    student, contact = student_with_contact
    # Pre-set customer ID so the customer creation mock isn't needed
    contact.helcim_customer_id = 'cust_existing_99'
    contact.save()

    invoice = _make_draft_invoice(student, school)
    lesson = _make_confirmed_lesson(student, teacher_user, school)
    invoice.lessons.add(lesson)

    with patch('billing.services.helcim_client.requests.post') as mock_post, \
         patch('billing.services.email_service.PreBillingEmailService.send_payment_request') as mock_email:
        mock_post.return_value = _helcim_create_invoice_ok()
        mock_email.return_value = (True, 'sent')

        url = reverse('management_pre_billing_send', kwargs={'invoice_id': invoice.id})
        response = management_client.post(url, format='json')

    invoice.refresh_from_db()
    assert invoice.status == 'sent'


# ---------------------------------------------------------------------------
# Tests — send all (BILL-05 bulk)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_send_all_partial_failure(management_client, school, teacher_user, db):
    """
    POST send-all processes invoices sequentially; one HelcimAPIError captured in 'failed'.
    BILL-05: partial failure returns summary {sent: N, failed: [{student_id, student_name, error}]}.
    """
    # Create 3 students with contacts and draft invoices
    invoices = []
    for i in range(3):
        student = User.objects.create_user(
            email=f"send_all_student_{i}@prebilling.test",
            password="pass",
            user_type="student",
            first_name=f"Student{i}",
            last_name="SendAll",
            school=school,
            is_approved=True,
        )
        BillableContact.objects.create(
            student=student,
            school=school,
            is_primary=True,
            first_name=f"Contact{i}",
            last_name="SendAll",
            email=f"contact_send_all_{i}@prebilling.test",
            phone="555-0300",
            street_address="123 Test St",
            city="Toronto",
            province="ON",
            postal_code="M5H 2N2",
            helcim_customer_id=f'cust_{i}',  # pre-set to skip customer creation
        )
        invoice = _make_draft_invoice(student, school)
        lesson = _make_confirmed_lesson(
            student, teacher_user, school,
            lesson_date=date(2026, 6, 3 + i)
        )
        invoice.lessons.add(lesson)
        invoices.append(invoice)

    def post_side_effect(*args, **kwargs):
        """2nd invoice's send fails."""
        if post_side_effect.call_count == 2:
            post_side_effect.call_count += 1
            raise HelcimAPIError('Helcim server error', status_code=500)
        post_side_effect.call_count += 1
        return _helcim_create_invoice_ok()

    post_side_effect.call_count = 1

    with patch('billing.services.helcim_client.requests.post', side_effect=post_side_effect), \
         patch('billing.services.email_service.PreBillingEmailService.send_payment_request',
               return_value=(True, 'sent')):

        url = reverse('management_pre_billing_send_all')
        response = management_client.post(url, format='json')

    assert response.status_code == 200
    assert response.data['sent'] == 2
    assert len(response.data['failed']) == 1
    failed_entry = response.data['failed'][0]
    assert 'student_id' in failed_entry
    assert 'student_name' in failed_entry
    assert 'error' in failed_entry


# ---------------------------------------------------------------------------
# Tests — remove lesson / void + recreate (BILL-08, BILL-09)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_remove_lesson(management_client, school, teacher_user, student_with_contact):
    """
    POST remove-lesson voids old Helcim invoice, creates new one, transitions to adjusted.
    BILL-08: invoice.status == 'adjusted'; lessons.count reduced; helcim_invoice_id updated.
    """
    student, contact = student_with_contact
    contact.helcim_customer_id = 'cust_existing_88'
    contact.save()

    invoice = PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='sent',
        amount=Decimal('180.00'),
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        helcim_invoice_id='inv_old_456',
        payment_token='tok_old_xyz',
    )
    lesson_dates = [date(2026, 6, 3), date(2026, 6, 10), date(2026, 6, 17)]
    lessons_created = []
    for d in lesson_dates:
        lesson = _make_confirmed_lesson(student, teacher_user, school, lesson_date=d)
        invoice.lessons.add(lesson)
        lessons_created.append(lesson)

    lesson_to_remove = lessons_created[0]

    new_invoice_response = Mock(
        ok=True,
        status_code=200,
        json=lambda: {'invoiceId': 'inv_new_789', 'token': 'tok_new_xyz', 'invoiceNumber': '002'},
        text='',
    )

    with patch('billing.services.helcim_client.requests.put') as mock_put, \
         patch('billing.services.helcim_client.requests.post') as mock_post, \
         patch('billing.services.email_service.PreBillingEmailService.send_payment_request') as mock_email:
        mock_put.return_value = _helcim_cancel_invoice_ok()
        mock_post.return_value = new_invoice_response
        mock_email.return_value = (True, 'sent')

        url = reverse('management_pre_billing_remove_lesson', kwargs={'invoice_id': invoice.id})
        response = management_client.post(url, data={'lesson_id': lesson_to_remove.id}, format='json')

    assert response.status_code == 200

    invoice.refresh_from_db()
    assert invoice.status == 'adjusted'
    assert invoice.lessons.count() == 2
    assert invoice.helcim_invoice_id == 'inv_new_789'


@pytest.mark.django_db
def test_void_failure_inline_error(management_client, school, teacher_user, student_with_contact):
    """
    POST remove-lesson returns 400 with 'Cannot void' error when cancel fails.
    BILL-09: void failure must return inline error, invoice status unchanged.
    """
    student, contact = student_with_contact
    contact.helcim_customer_id = 'cust_existing_77'
    contact.save()

    invoice = PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='sent',
        amount=Decimal('120.00'),
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        helcim_invoice_id='inv_settled_321',
        payment_token='tok_settled_abc',
    )
    lesson = _make_confirmed_lesson(student, teacher_user, school)
    invoice.lessons.add(lesson)

    with patch('billing.services.helcim_client.requests.put') as mock_put:
        mock_put.return_value = _helcim_cancel_invoice_fail()

        url = reverse('management_pre_billing_remove_lesson', kwargs={'invoice_id': invoice.id})
        response = management_client.post(url, data={'lesson_id': lesson.id}, format='json')

    assert response.status_code == 400
    assert 'Cannot void' in response.data['error']

    invoice.refresh_from_db()
    assert invoice.status == 'sent'  # unchanged
