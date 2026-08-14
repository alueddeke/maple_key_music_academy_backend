"""Trigger tests: rejection/submission signals, exception + reminder services, delivery opt-in."""

from datetime import date, time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

from billing.models import BatchLessonItem, MonthlyInvoiceBatch
from notifications.models import Notification, NotificationPreference
from notifications.services import (
    INVOICE_REMINDER_DAY,
    notify,
    notify_exception_marked,
    send_invoice_reminders,
)

User = get_user_model()


@pytest.fixture
def submitted_batch(teacher_user, school, db):
    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=school,
        month=6,
        year=2026,
        status='submitted',
    )


@pytest.fixture
def second_manager(school, db):
    return User.objects.create_user(
        email="manager2@test.com",
        password="testpass123",
        user_type="management",
        first_name="Second",
        last_name="Manager",
        school=school,
        is_approved=True,
    )


@pytest.fixture
def approved_batch(teacher_user, school, db):
    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=school,
        month=6,
        year=2026,
        status='approved',
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
class TestBatchSubmittedSignal:
    def test_submit_transition_notifies_each_manager(
        self, teacher_user, school, management_user, second_manager
    ):
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=6, year=2026, status='draft'
        )
        batch.status = 'submitted'
        batch.save()

        notifs = Notification.objects.filter(type='batch_submitted')
        assert notifs.count() == 2
        assert {n.user for n in notifs} == {management_user, second_manager}
        for n in notifs:
            assert n.link_url == f'/management/payroll/{batch.id}'
            assert 'June 2026' in n.message
            assert teacher_user.get_full_name() in n.message
            assert n.read_status is False

    def test_resubmit_after_rejection_fires_again(
        self, submitted_batch, management_user
    ):
        # Reject: submitted -> draft with a reason (fires rejection, not submit)
        submitted_batch.status = 'draft'
        submitted_batch.rejection_reason = 'Missing lesson dates'
        submitted_batch.save()
        assert not Notification.objects.filter(type='batch_submitted').exists()

        # Resubmit: draft -> submitted (mirrors batch_submit clearing the reason)
        submitted_batch.status = 'submitted'
        submitted_batch.rejection_reason = ''
        submitted_batch.save()
        assert Notification.objects.filter(
            user=management_user, type='batch_submitted'
        ).count() == 1

    def test_non_transition_save_does_not_fire(
        self, submitted_batch, management_user
    ):
        submitted_batch.save()  # submitted -> submitted
        assert not Notification.objects.filter(type='batch_submitted').exists()

    def test_approval_does_not_fire(self, submitted_batch, management_user):
        submitted_batch.status = 'approved'
        submitted_batch.save()
        assert not Notification.objects.filter(type='batch_submitted').exists()

    def test_batch_created_as_submitted_does_not_fire(
        self, teacher_user, school, management_user
    ):
        MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=7, year=2026,
            status='submitted',
        )
        assert not Notification.objects.filter(type='batch_submitted').exists()

    def test_inactive_manager_not_notified(
        self, teacher_user, school, management_user
    ):
        management_user.is_active = False
        management_user.save()
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=6, year=2026, status='draft'
        )
        batch.status = 'submitted'
        batch.save()
        assert not Notification.objects.filter(type='batch_submitted').exists()


@pytest.mark.django_db
class TestExceptionMarkedService:
    def test_notifies_each_manager(
        self, approved_batch, teacher_user, management_user, second_manager
    ):
        created = notify_exception_marked(approved_batch, 'status confirmed -> waived')
        assert len(created) == 2
        assert {n.user for n in created} == {management_user, second_manager}
        for n in created:
            assert n.type == 'exception_marked'
            assert n.link_url == f'/management/payroll/{approved_batch.id}'
            assert 'June 2026' in n.message
            assert teacher_user.get_full_name() in n.message

    def test_dedupes_on_unread_same_link(self, approved_batch, management_user):
        assert len(notify_exception_marked(approved_batch, 'first mark')) == 1
        assert notify_exception_marked(approved_batch, 'second mark') == []
        assert Notification.objects.filter(
            user=management_user, type='exception_marked'
        ).count() == 1

    def test_fires_again_after_read(self, approved_batch, management_user):
        first = notify_exception_marked(approved_batch, 'first mark')[0]
        first.read_status = True
        first.save()
        assert len(notify_exception_marked(approved_batch, 'later mark')) == 1

    def test_different_batch_not_deduped(
        self, approved_batch, teacher_user, school, management_user
    ):
        other = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=7, year=2026,
            status='approved',
        )
        assert len(notify_exception_marked(approved_batch, 'june mark')) == 1
        assert len(notify_exception_marked(other, 'july mark')) == 1


@pytest.mark.django_db
class TestExceptionMarkedViewPath:
    """Exception notifications through teacher_batch_adjustment_item PATCH."""

    def _make_item(self, batch, student, status='confirmed'):
        return BatchLessonItem.objects.create(
            batch=batch,
            student=student,
            scheduled_date=date(2026, 6, 5),  # past, so status guards allow it
            start_time=time(10, 0),
            duration=Decimal('1.0'),
            lesson_type='online',
            teacher_rate=Decimal('45.00'),
            student_rate=Decimal('60.00'),
            status=status,
        )

    def test_adjustment_patch_creates_notification(
        self, teacher_client, teacher_user, student_user, school,
        school_settings, management_user,
    ):
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=6, year=2026,
            status='approved',
        )
        item = self._make_item(batch, student_user)
        url = reverse(
            'teacher_batch_adjustment_item',
            kwargs={'batch_id': batch.id, 'item_id': item.id},
        )

        response = teacher_client.patch(url, {'status': 'waived'}, format='json')

        assert response.status_code == 200
        assert Notification.objects.filter(
            user=management_user,
            type='exception_marked',
            link_url=f'/management/payroll/{batch.id}',
        ).count() == 1

    def test_noop_patch_does_not_notify(
        self, teacher_client, teacher_user, student_user, school,
        school_settings, management_user,
    ):
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=6, year=2026,
            status='approved',
        )
        item = self._make_item(batch, student_user)
        url = reverse(
            'teacher_batch_adjustment_item',
            kwargs={'batch_id': batch.id, 'item_id': item.id},
        )

        # Same status, same date — nothing actually changed
        response = teacher_client.patch(url, {'status': 'confirmed'}, format='json')

        assert response.status_code == 200
        assert not Notification.objects.filter(type='exception_marked').exists()


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
