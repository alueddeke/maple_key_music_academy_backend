from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class Notification(models.Model):
    """A persistent in-app notification shown in the header bell dropdown.

    Distinct from transient sonner toasts (Phase 14 unified those) — bell
    notifications persist until read and can deep-link to the page where
    the user must act.

    No django-simple-history here on purpose: notifications are high-volume,
    append-mostly rows whose only mutation is the read flag — audit shadow
    tables would double storage for no value.
    """
    TYPE_CHOICES = [
        ('invoice_rejected', 'Invoice Rejected'),
        ('invoice_reminder', 'Invoice Submission Reminder'),
        ('batch_submitted', 'Invoice Submitted'),
        ('exception_marked', 'Exception Marked'),
        ('general', 'General'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    school = models.ForeignKey(
        'billing.School',
        on_delete=models.PROTECT,
        related_name='notifications',
    )
    message = models.CharField(max_length=500)
    type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='general')
    read_status = models.BooleanField(default=False)
    link_url = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Frontend route the notification deep-links to (e.g. /invoice)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'read_status']),
        ]

    def save(self, *args, **kwargs):
        # School always mirrors the recipient's school (multi-tenancy convention)
        if not self.school_id and self.user_id:
            self.school = self.user.school
        super().save(*args, **kwargs)

    def __str__(self):
        state = 'read' if self.read_status else 'unread'
        return f"[{self.get_type_display()}] {self.user.email} — {self.message[:50]} ({state})"


class NotificationPreference(models.Model):
    """Per-user opt-in switches for notification delivery channels.

    In-app (bell) notifications are always created; email/SMS delivery only
    happens when the user opted in here. SMS additionally requires a real
    provider (see notifications.sms — currently a no-op stub).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preference',
    )
    email_enabled = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def __str__(self):
        return (
            f"Prefs: {self.user.email} — email={'on' if self.email_enabled else 'off'}, "
            f"sms={'on' if self.sms_enabled else 'off'}"
        )
