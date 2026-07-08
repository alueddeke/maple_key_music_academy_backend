"""Send monthly invoice-submission reminders to teachers.

NEEDS-SCHEDULING: this stack has no cron/beat scheduler — this command must
be scheduled externally (host cron, GitHub Action, or a future Celery beat).
Safe to run daily: it no-ops before INVOICE_REMINDER_DAY and sends at most
one reminder per teacher per month.

Usage:
    python manage.py send_invoice_reminders
"""

from django.core.management.base import BaseCommand

from notifications.services import INVOICE_REMINDER_DAY, send_invoice_reminders


class Command(BaseCommand):
    help = (
        "Notify teachers who have not submitted this month's invoice batch "
        f"(fires on/after day {INVOICE_REMINDER_DAY} of the month, once per teacher)"
    )

    def handle(self, *args, **options):
        created = send_invoice_reminders()
        if not created:
            self.stdout.write(
                f"No reminders sent (before day {INVOICE_REMINDER_DAY}, "
                "or all teachers submitted / already reminded)."
            )
            return
        for notification in created:
            self.stdout.write(f"Reminded {notification.user.email}")
        self.stdout.write(self.style.SUCCESS(f"{len(created)} reminder(s) sent."))
