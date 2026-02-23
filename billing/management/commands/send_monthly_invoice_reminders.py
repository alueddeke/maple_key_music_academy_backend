from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from billing.models import User, MonthlyInvoiceBatch
import calendar


class Command(BaseCommand):
    help = 'Send monthly invoice reminders to teachers on 25th of month'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force send emails even if not the 25th (for testing)',
        )

    def handle(self, *args, **options):
        today = timezone.now().date()
        force_send = options.get('force', False)

        # Only run on 25th of month unless forced
        if today.day != 25 and not force_send:
            self.stdout.write(
                self.style.WARNING(f'Not the 25th (today is {today}). Skipping. Use --force to send anyway.')
            )
            return

        # Get current month/year
        current_month = today.month
        current_year = today.year

        # Get all active teachers
        teachers = User.objects.filter(
            user_type='teacher',
            is_active=True,
            is_approved=True
        )

        sent_count = 0
        skipped_count = 0

        for teacher in teachers:
            # Check if teacher has recurring schedules
            has_schedules = teacher.teaching_schedules.filter(is_active=True).exists()

            if not has_schedules:
                self.stdout.write(
                    self.style.WARNING(f'Skipping {teacher.email} - no active recurring schedules')
                )
                skipped_count += 1
                continue

            # Check if batch already exists
            batch_exists = MonthlyInvoiceBatch.objects.filter(
                teacher=teacher,
                month=current_month,
                year=current_year
            ).exists()

            # Email message
            subject = f'Monthly Invoice Reminder - {calendar.month_name[current_month]} {current_year}'

            if batch_exists:
                message = f"""Hi {teacher.get_full_name()},

This is a reminder to review and submit your monthly invoice for {calendar.month_name[current_month]} {current_year}.

You have an existing draft invoice. Please log in to review, mark lesson statuses, and submit.

Login: {settings.FRONTEND_URL}/login
Invoice Page: {settings.FRONTEND_URL}/invoice

Thank you!
Maple Key Music Academy
"""
            else:
                message = f"""Hi {teacher.get_full_name()},

This is a reminder to create and submit your monthly invoice for {calendar.month_name[current_month]} {current_year}.

Please log in to review your scheduled lessons, mark attendance, and submit your invoice.

Login: {settings.FRONTEND_URL}/login
Invoice Page: {settings.FRONTEND_URL}/invoice

Thank you!
Maple Key Music Academy
"""

            # Send email
            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[teacher.email],
                    fail_silently=False,
                )
                sent_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Sent reminder to {teacher.email}')
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'✗ Failed to send to {teacher.email}: {str(e)}')
                )

        # Summary
        self.stdout.write(
            self.style.SUCCESS(f'\nDone! Sent {sent_count} reminders, skipped {skipped_count} teachers.')
        )
