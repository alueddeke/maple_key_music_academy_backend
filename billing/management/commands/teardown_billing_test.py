"""
Delete all billing test data tagged with @maplekeytest.com.

Safe to run any time — only touches records owned by @maplekeytest.com users.
Does NOT touch real teacher/student data.

Usage:
    docker compose exec api python manage.py teardown_billing_test

    # Dry run (show what would be deleted without deleting)
    docker compose exec api python manage.py teardown_billing_test --dry-run
"""

import calendar
import datetime

from django.core.management.base import BaseCommand

from billing.models import (
    User,
    School,
    MonthlyInvoiceBatch,
    BatchLessonItem,
    BillableContact,
    StudentInvoice,
    Invoice,
    Lesson,
    PreBillingInvoice,
    StudentCreditAccount,
    CreditTransaction,
    SchoolMonthlyExpenses,
    SchoolExpenseItem,
)

TEST_DOMAIN = '@maplekeytest.com'


class Command(BaseCommand):
    help = (
        'Delete all billing test data tagged with @maplekeytest.com. '
        'Safe — never touches real records.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        school = School.objects.first()

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — nothing will be deleted.\n'))

        # ---- Identify test users ----
        test_teachers = list(User.objects.filter(email__endswith=TEST_DOMAIN, user_type='teacher'))
        test_students = list(User.objects.filter(email__endswith=TEST_DOMAIN, user_type='student'))

        if not test_teachers and not test_students:
            self.stdout.write('No test data found.')
            return

        self.stdout.write(
            f'Found {len(test_teachers)} test teacher(s) and {len(test_students)} test student(s).\n'
        )

        student_ids = [s.id for s in test_students]
        teacher_ids = [t.id for t in test_teachers]

        # ---- Collect batch IDs before deletion ----
        batches = MonthlyInvoiceBatch.objects.filter(teacher_id__in=teacher_ids)
        batch_ids = list(batches.values_list('id', flat=True))
        batch_periods = [(b.month, b.year) for b in batches]

        # ---- Count for summary ----
        lesson_count = Lesson.objects.filter(teacher_id__in=teacher_ids).count()
        batch_lesson_items = BatchLessonItem.objects.filter(batch_id__in=batch_ids).count()
        student_invoice_count = StudentInvoice.objects.filter(batch_id__in=batch_ids).count()
        teacher_invoice_count = Invoice.objects.filter(teacher_id__in=teacher_ids).count()
        pre_billing_count = PreBillingInvoice.objects.filter(student_id__in=student_ids).count()
        credit_tx_count = CreditTransaction.objects.filter(
            account__student_id__in=student_ids
        ).count()
        credit_acct_count = StudentCreditAccount.objects.filter(student_id__in=student_ids).count()
        contact_count = BillableContact.objects.filter(student_id__in=student_ids).count()

        # Expenses for test periods (only those exclusively from test data)
        # Safe to delete if there are no non-test approved batches for the same period
        expense_periods_to_delete = []
        if school:
            for month, year in set(batch_periods):
                period_start = datetime.date(year, month, 1)
                period_end = datetime.date(year, month, calendar.monthrange(year, month)[1])
                non_test_batch_exists = MonthlyInvoiceBatch.objects.filter(
                    school=school,
                    month=month,
                    year=year,
                    status='approved',
                ).exclude(teacher_id__in=teacher_ids).exists()
                if not non_test_batch_exists:
                    has_old = SchoolMonthlyExpenses.objects.filter(
                        school=school, period_start=period_start, period_end=period_end,
                    ).exists()
                    has_new = SchoolExpenseItem.objects.filter(
                        school=school, period_start=period_start, period_end=period_end,
                    ).exists()
                    if has_old or has_new:
                        expense_periods_to_delete.append((period_start, period_end))

        self.stdout.write(f'Will delete:')
        self.stdout.write(f'  {len(batch_ids)} batch(es)')
        self.stdout.write(f'  {batch_lesson_items} batch lesson items')
        self.stdout.write(f'  {lesson_count} lesson records')
        self.stdout.write(f'  {student_invoice_count} student invoices')
        self.stdout.write(f'  {teacher_invoice_count} teacher invoices')
        self.stdout.write(f'  {pre_billing_count} pre-billing invoices')
        self.stdout.write(f'  {credit_tx_count} credit transactions')
        self.stdout.write(f'  {credit_acct_count} credit accounts')
        self.stdout.write(f'  {contact_count} billable contacts')
        self.stdout.write(f'  {len(expense_periods_to_delete)} monthly expense record(s)')
        self.stdout.write(f'  {len(test_students)} test student(s)')
        self.stdout.write(f'  {len(test_teachers)} test teacher(s)')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDry run complete. Nothing deleted.'))
            return

        # ---- Delete in dependency order ----

        # 1. Credit transactions
        CreditTransaction.objects.filter(account__student_id__in=student_ids).delete()

        # 2. Credit accounts
        StudentCreditAccount.objects.filter(student_id__in=student_ids).delete()

        # 3. Pre-billing invoices
        PreBillingInvoice.objects.filter(student_id__in=student_ids).delete()

        # 4. Student invoices (M2M lesson_items auto-cleared)
        StudentInvoice.objects.filter(batch_id__in=batch_ids).delete()

        # 5. BatchLessonItems (FK to Lesson — clear created_lesson before deleting lessons)
        BatchLessonItem.objects.filter(batch_id__in=batch_ids).update(created_lesson=None)

        # 6. Lessons
        Lesson.objects.filter(teacher_id__in=teacher_ids).delete()

        # 7. Teacher Invoices (unlink from batches first to avoid SET_NULL cascading issues)
        MonthlyInvoiceBatch.objects.filter(id__in=batch_ids).update(invoice=None)
        Invoice.objects.filter(teacher_id__in=teacher_ids).delete()
        Invoice.objects.filter(student_id__in=student_ids).delete()

        # 8. Batches
        MonthlyInvoiceBatch.objects.filter(id__in=batch_ids).delete()

        # 9. Expenses (only periods with no remaining non-test data)
        if school:
            for period_start, period_end in expense_periods_to_delete:
                SchoolMonthlyExpenses.objects.filter(
                    school=school, period_start=period_start, period_end=period_end,
                ).delete()
                SchoolExpenseItem.objects.filter(
                    school=school, period_start=period_start, period_end=period_end,
                ).delete()

        # 10. Billable contacts
        BillableContact.objects.filter(student_id__in=student_ids).delete()

        # 11. Students
        User.objects.filter(id__in=student_ids).delete()

        # 12. Teachers
        User.objects.filter(id__in=teacher_ids).delete()

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('✓ All test data deleted.'))
        self.stdout.write(
            f'  Seed fresh data with:  '
            f'docker compose exec api python manage.py seed_billing_test --scenario=full'
        )
