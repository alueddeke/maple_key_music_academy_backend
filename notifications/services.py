"""Notification creation + delivery service.

Creating the in-app Notification row is the primary effect and must never
fail because a delivery channel failed — email/SMS errors are logged and
swallowed. Email goes through Django's mail framework, which is already
backed by Resend (billing.resend_backend.ResendEmailBackend); no new mail
library is used.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import Notification, NotificationPreference
from .sms import get_sms_provider

logger = logging.getLogger(__name__)

# Day of month on which teachers who have not yet submitted their monthly
# invoice batch get a reminder. Product decision pending (flagged for Bill);
# 25 leaves roughly a week before month-end billing.
INVOICE_REMINDER_DAY = 25


def notify(user, message, notification_type='general', link_url=''):
    """Create an in-app notification and deliver via opted-in channels."""
    notification = Notification.objects.create(
        user=user,
        school=user.school,
        message=message,
        type=notification_type,
        link_url=link_url,
    )

    prefs = NotificationPreference.objects.filter(user=user).first()
    if prefs and prefs.email_enabled:
        _send_email(user, message)
    if prefs and prefs.sms_enabled:
        _send_sms(user, message)

    return notification


def _send_email(user, message):
    try:
        send_mail(
            subject='Maple Key Music Academy — Notification',
            message=(
                f"Hi {user.get_full_name()},\n\n"
                f"{message}\n\n"
                f"Log in to view details.\n\n"
                f"Maple Key Music Academy"
            ),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@maplekey.com'),
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Notification email delivery failed for %s", user.email)


def _send_sms(user, message):
    phone = getattr(user, 'phone_number', '') or ''
    if not phone:
        logger.info("SMS skipped for %s: no phone number on file", user.email)
        return
    try:
        get_sms_provider().send(phone, message)
    except Exception:
        logger.exception("Notification SMS delivery failed for %s", user.email)


def notify_batch_rejected(batch):
    """Fire the invoice-rejected notification for a teacher's monthly batch."""
    reason = (batch.rejection_reason or '').strip()
    message = (
        f"Your {batch.year}-{batch.month:02d} invoice was rejected and needs changes."
    )
    if reason:
        message += f" Reason: {reason}"
    return notify(
        batch.teacher,
        message[:500],
        notification_type='invoice_rejected',
        link_url='/invoice',
    )


def notify_invoice_rejected(invoice):
    """Fire the invoice-rejected notification for a legacy teacher invoice."""
    reason = (invoice.rejection_reason or '').strip()
    message = f"Your invoice {invoice.invoice_number or invoice.pk} was rejected."
    if reason:
        message += f" Reason: {reason}"
    return notify(
        invoice.teacher,
        message[:500],
        notification_type='invoice_rejected',
        link_url='/invoice',
    )


def send_invoice_reminders(today=None):
    """Remind teachers who have not submitted this month's invoice batch.

    Runs as a callable service so the management command (and, later, a real
    scheduler — none exists in this stack yet, flagged for GSD) can invoke it.
    Idempotent: at most one reminder per teacher per calendar month.
    Returns the list of notifications created.
    """
    from django.contrib.auth import get_user_model
    from billing.models import MonthlyInvoiceBatch

    User = get_user_model()
    today = today or timezone.localdate()
    if today.day < INVOICE_REMINDER_DAY:
        return []

    period = f"{today.year}-{today.month:02d}"
    created = []
    teachers = User.objects.filter(
        user_type='teacher', is_approved=True, is_active=True
    )
    for teacher in teachers:
        has_submitted = MonthlyInvoiceBatch.objects.filter(
            teacher=teacher,
            year=today.year,
            month=today.month,
            status__in=['submitted', 'approved'],
        ).exists()
        if has_submitted:
            continue

        # Dedupe on the period embedded in the message (not created_at),
        # so re-runs are safe regardless of when the reminder was created.
        already_reminded = Notification.objects.filter(
            user=teacher,
            type='invoice_reminder',
            message__contains=period,
        ).exists()
        if already_reminded:
            continue

        created.append(
            notify(
                teacher,
                (
                    f"You haven't submitted your {period} invoice yet. "
                    f"Please review and submit it before month end."
                ),
                notification_type='invoice_reminder',
                link_url='/invoice',
            )
        )
    return created
