"""
Reset a clean batch-send demo period (local dev only).

Wipes send runs + pre-billing invoices for the chosen period (test-domain
students only), zeroes their wallet credit so no draft lands at $0, and
creates fresh schedule-projected drafts — one click of "Send All" then
exercises the full run: snapshot -> worker -> Helcim test invoices -> emails.

Usage:
  docker exec maple_key_api python manage.py seed_send_run_demo             # next month, 5 drafts
  docker exec maple_key_api python manage.py seed_send_run_demo --month 11 --year 2026 --limit 8
"""
import calendar
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from billing.models import (
    BillableContact,
    InvoiceSendRun,
    PreBillingInvoice,
    RecurringLessonsSchedule,
    StudentCreditAccount,
    User,
)
from billing.services.invoice_sending import projected_items

TEST_DOMAIN = '@maplekeytest.com'


def _next_month(today):
    if today.month == 12:
        return today.year + 1, 1
    return today.year, today.month + 1


class Command(BaseCommand):
    help = 'Reset a clean pre-billing period with sendable drafts for batch-send testing.'

    def add_arguments(self, parser):
        parser.add_argument('--month', type=int, help='1-12 (default: next month)')
        parser.add_argument('--year', type=int, help='4-digit year (default: next month)')
        parser.add_argument('--limit', type=int, default=5,
                            help='How many drafts to create (default 5)')

    @transaction.atomic
    def handle(self, *args, **options):
        default_year, default_month = _next_month(date.today())
        month = options['month'] or default_month
        year = options['year'] or default_year
        period_start = date(year, month, 1)
        period_end = date(year, month, calendar.monthrange(year, month)[1])

        students = User.objects.filter(
            user_type='student', is_active=True, email__endswith=TEST_DOMAIN,
        )
        student_ids = list(students.values_list('id', flat=True))

        # Order matters: items PROTECT their invoices — runs (and their items)
        # go first, then the period's invoices.
        runs_deleted, _ = InvoiceSendRun.objects.filter(
            period_start=period_start, items__invoice__student_id__in=student_ids,
        ).distinct().delete()
        invoices_deleted, _ = PreBillingInvoice.objects.filter(
            student_id__in=student_ids, period_start=period_start,
        ).delete()

        # $0-after-credit drafts are unsendable by design — clear the wallets
        # so every demo draft has an amount owing.
        credits_zeroed = StudentCreditAccount.objects.filter(
            student_id__in=student_ids, balance__gt=0,
        ).update(balance=Decimal('0.00'))

        created = 0
        skipped = []
        for student in students.select_related('school').order_by('id'):
            if created >= options['limit']:
                break
            if not BillableContact.objects.filter(student=student, is_primary=True).exists():
                skipped.append((student.get_full_name(), 'no primary contact'))
                continue
            if not RecurringLessonsSchedule.objects.filter(
                student=student, school=student.school, is_active=True,
            ).exists():
                skipped.append((student.get_full_name(), 'no active schedule'))
                continue

            invoice = PreBillingInvoice(
                student=student, school=student.school, status='draft',
                period_start=period_start, period_end=period_end,
            )
            gross = sum(
                (item['rate'] * item['duration'] for item in projected_items(invoice)),
                Decimal('0.00'),
            ).quantize(Decimal('0.01'))
            if gross <= 0:
                skipped.append((student.get_full_name(), 'schedule projects no lessons this month'))
                continue
            invoice.amount = gross
            invoice.save()
            created += 1

        label = period_start.strftime('%B %Y')
        self.stdout.write(self.style.SUCCESS(
            f'{label}: wiped {runs_deleted} run rows + {invoices_deleted} invoice rows, '
            f'zeroed {credits_zeroed} credit balance(s), created {created} sendable drafts.'
        ))
        for name, why in skipped:
            self.stdout.write(f'  skipped {name}: {why}')
        self.stdout.write(
            f'Test: Student Billing -> {label} -> Send All. Worker logs: '
            f'docker logs -f maple_key_worker. Every email lands in your own inbox.'
        )
