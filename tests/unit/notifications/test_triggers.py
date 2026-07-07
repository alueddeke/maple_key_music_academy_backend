"""Trigger tests: rejection signals, reminder service, delivery opt-in."""

from datetime import date

import pytest
from django.core import mail

from billing.models import MonthlyInvoiceBatch
from notifications.models import Notification, NotificationPreference
from notifications.services import (
    INVOICE_REMINDER_DAY,
    notify,
    send_invoice_reminders,
)


@pytest.fixture
def submitted_batch(teacher_user, school, db):
    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=school,
        month=6,
        year=2026,
        status='submitted',
    )


@pytest.mark.django_db
class TestBatchRejectionSignal:
    def test_rejection_transition_creates_notification(
        self, submitted_batch, teacher_user
    ):
        # Mirror management_reject_batch: submitted -> draft + rejection_reason
        submitted_batch.status = 'draft'
        submitted_batch.rejection_reason = 'Missing lesson dates'
        submitted_batch.save()

        notification = Notification.objects.get(
            user=teacher_user, type='invoice_rejected'
        )
        assert 'rejected' in notification.message
        assert 'Missing lesson dates' in notification.message
        assert notification.link_url == '/invoice'
        assert notification.read_status is False

    def test_plain_draft_transition_does_not_fire(self, submitted_batch, teacher_user):
        # submitted -> draft WITHOUT a rejection reason is not a rejection
        submitted_batch.status = 'draft'
        submitted_batch.save()
        assert not Notification.objects.filter(user=teacher_user).exists()

    def test_approval_does_not_fire(self, submitted_batch, teacher_user):
        submitted_batch.status = 'approved'
        submitted_batch.save()
        assert not Notification.objects.filter(
            user=teacher_user, type='invoice_rejected'
        ).exists()

    def test_batch_creation_does_not_fire(self, teacher_user, school):
        MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=7, year=2026, status='draft'
        )
        assert not Notification.objects.filter(user=teacher_user).exists()


@pytest.mark.django_db
class TestInvoiceReminders:
    REMINDER_DATE = date(2026, 6, INVOICE_REMINDER_DAY)

    def test_reminds_teacher_without_submitted_batch(self, teacher_user):
        created = send_invoice_reminders(today=self.REMINDER_DATE)
        assert len(created) == 1
        assert created[0].user == teacher_user
        assert created[0].type == 'invoice_reminder'
        assert created[0].link_url == '/invoice'

    def test_no_reminder_before_reminder_day(self, teacher_user):
        created = send_invoice_reminders(
            today=date(2026, 6, INVOICE_REMINDER_DAY - 1)
        )
        assert created == []

    def test_skips_teacher_with_submitted_batch(self, teacher_user, submitted_batch):
        created = send_invoice_reminders(today=self.REMINDER_DATE)
        assert created == []

    def test_draft_batch_still_gets_reminder(self, teacher_user, school):
        MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=6, year=2026, status='draft'
        )
        created = send_invoice_reminders(today=self.REMINDER_DATE)
        assert len(created) == 1

    def test_idempotent_within_month(self, teacher_user):
        assert len(send_invoice_reminders(today=self.REMINDER_DATE)) == 1
        assert send_invoice_reminders(today=self.REMINDER_DATE) == []
        assert (
            send_invoice_reminders(today=date(2026, 6, INVOICE_REMINDER_DAY + 3)) == []
        )

    def test_skips_unapproved_teacher(self, unapproved_teacher):
        created = send_invoice_reminders(today=self.REMINDER_DATE)
        assert unapproved_teacher not in [n.user for n in created]


@pytest.mark.django_db
class TestDeliveryOptIn:
    @pytest.fixture(autouse=True)
    def _locmem_email(self, settings):
        settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

    def test_no_email_without_opt_in(self, teacher_user):
        notify(teacher_user, 'hello')
        assert len(mail.outbox) == 0

    def test_email_sent_when_opted_in(self, teacher_user):
        NotificationPreference.objects.create(user=teacher_user, email_enabled=True)
        notify(teacher_user, 'Your invoice was rejected.')
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [teacher_user.email]
        assert 'Your invoice was rejected.' in mail.outbox[0].body

    def test_notification_created_even_if_email_fails(self, teacher_user, monkeypatch):
        NotificationPreference.objects.create(user=teacher_user, email_enabled=True)

        def boom(*args, **kwargs):
            raise RuntimeError('smtp down')

        monkeypatch.setattr('notifications.services.send_mail', boom)
        notification = notify(teacher_user, 'still created')
        assert Notification.objects.filter(pk=notification.pk).exists()

    def test_sms_opt_in_uses_noop_provider_without_error(self, teacher_user):
        teacher_user.phone_number = '555-0100'
        teacher_user.save()
        NotificationPreference.objects.create(user=teacher_user, sms_enabled=True)
        notification = notify(teacher_user, 'sms path')
        assert Notification.objects.filter(pk=notification.pk).exists()
        assert len(mail.outbox) == 0
