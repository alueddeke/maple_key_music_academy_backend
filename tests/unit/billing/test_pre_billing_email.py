"""
MAP-222: the parent invoice email is sent from the school's billing address,
carries the school's Reply-To when one is set, and stays a plain-text message
with exactly one payment URL.
"""
from decimal import Decimal
from email.utils import parseaddr

import pytest
from django.conf import settings
from django.core import mail

from billing.services.email_service import PreBillingEmailService

PAYMENT_URL = 'https://example.myhelcim.com/order/?token=abc123'
LESSON_DATES = ['2026-10-04', '2026-10-11']


def _send(school):
    return PreBillingEmailService.send_payment_request(
        'parent@example.com',
        'Pat Parent',
        school,
        'October 2026',
        Decimal('120.00'),
        LESSON_DATES,
        PAYMENT_URL,
    )


@pytest.mark.django_db
def test_sent_from_school_name_at_invoice_address(school_settings):
    school = school_settings.school

    ok, _ = _send(school)

    assert ok
    assert len(mail.outbox) == 1
    name, address = parseaddr(mail.outbox[0].from_email)
    assert name == school.name
    assert address == settings.INVOICE_EMAIL_ADDRESS


@pytest.mark.django_db
def test_subject_names_school_and_period(school_settings):
    school = school_settings.school

    _send(school)

    assert mail.outbox[0].subject == f'{school.name} — invoice for October 2026'


@pytest.mark.django_db
def test_reply_to_is_the_school_setting_when_set(school_settings):
    school_settings.invoice_reply_to_email = 'office@example.org'
    school_settings.save()

    _send(school_settings.school)

    assert mail.outbox[0].reply_to == ['office@example.org']


@pytest.mark.django_db
def test_no_reply_to_when_setting_blank(school_settings):
    assert school_settings.invoice_reply_to_email == ''

    _send(school_settings.school)

    assert mail.outbox[0].reply_to == []


@pytest.mark.django_db
def test_no_reply_to_when_school_has_no_settings_row(school):
    _send(school)

    assert mail.outbox[0].reply_to == []


@pytest.mark.django_db
def test_plain_text_body_with_exactly_one_payment_url(school_settings):
    _send(school_settings.school)

    message = mail.outbox[0].message()
    assert message.get_content_type() == 'text/plain'
    assert mail.outbox[0].body.count(PAYMENT_URL) == 1
    for lesson_date in LESSON_DATES:
        assert lesson_date in mail.outbox[0].body
