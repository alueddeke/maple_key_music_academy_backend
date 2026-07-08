"""
Seed billing test data for dashboard UI testing.

All test data is tagged with the @maplekeytest.com email domain so it can be
cleanly wiped by teardown_billing_test without touching real records.

Usage:
    # Basic: approved batch for current month (draft→submitted→approved + StudentInvoices + teacher Invoice)
    docker compose exec api python manage.py seed_billing_test

    # Specific month/year
    docker compose exec api python manage.py seed_billing_test --month=9 --year=2026

    # Draft only (teacher can still edit)
    docker compose exec api python manage.py seed_billing_test --status=draft

    # Submitted (waiting for management approval)
    docker compose exec api python manage.py seed_billing_test --status=submitted

    # Approved + credits applied + expenses + paid teacher invoice (full dashboard scenario)
    docker compose exec api python manage.py seed_billing_test --scenario=full

    # Multiple periods (3 months) for testing prev/next navigation
    docker compose exec api python manage.py seed_billing_test --scenario=multi

    # Submitted batch + pre-billing invoices sent (billable contact can "pay")
    # Use this to test the full approval+credit flow interactively
    docker compose exec api python manage.py seed_billing_test --scenario=pre-billed

    # Show what test data currently exists
    docker compose exec api python manage.py seed_billing_test --list

Notes
-----
- Re-running the command for the same month REPLACES existing test data for that month.
- Students and teacher are reused across months if they already exist.
- Scenario 'full': adds PreBillingInvoice (credits applied), SchoolMonthlyExpenses,
  and marks the teacher invoice as paid with a reference number.
- Scenario 'multi': seeds 3 consecutive months ending at --month/--year (approved, no credits).
"""

import random
import datetime
import calendar
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from django.db import transaction

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
    SchoolMonthlyExpenses,
    SchoolSettings,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_DOMAIN = '@maplekeytest.com'

TEACHER_EMAIL = f'testteacher{TEST_DOMAIN}'
STUDENT_EMAILS = [
    f'student.sofia{TEST_DOMAIN}',
    f'student.maya{TEST_DOMAIN}',
    f'student.theo{TEST_DOMAIN}',
]

LESSON_START_TIMES = [
    datetime.time(9, 0), datetime.time(10, 0), datetime.time(11, 0),
    datetime.time(14, 0), datetime.time(15, 0), datetime.time(16, 0),
    datetime.time(17, 0), datetime.time(18, 0),
]

TEACHER_NOTES_POOL = [
    'Worked on C major scale — good progress.',
    'Reviewed sight-reading exercises.',
    'Introduced chord progressions I-IV-V.',
    'Focused on hand positioning and posture.',
    'Practiced scales and arpeggios.',
    '',
]

STUDENT_DATA = [
    {'first': 'Sofia',  'last': 'Ramirez',  'parent_first': 'Maria'},
    {'first': 'Maya',   'last': 'Chen',     'parent_first': 'Wei'},
    {'first': 'Theo',   'last': 'Kowalski', 'parent_first': 'Anna'},
]

TORONTO_STREETS = [
    '123 Bloor St W', '456 Spadina Ave', '789 Queen St E',
    '321 King St W', '654 Yonge St',
]
TORONTO_CITIES = ['Toronto', 'North York', 'Scarborough']
TORONTO_POSTAL_CODES = ['M5V 1J2', 'M6G 3B4', 'M4K 2E6', 'M6P 1Z5', 'M5R 1Z1']

PASSWORD = 'testpass123'

# Lesson mix: durations and types per student
LESSON_CONFIGS = [
    {'duration_min': 60, 'lesson_type': 'online'},
    {'duration_min': 45, 'lesson_type': 'in_person'},
    {'duration_min': 30, 'lesson_type': 'online'},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_range(month, year):
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, 1), datetime.date(year, month, last_day)


def _prev_month(month, year):
    if month == 1:
        return 12, year - 1
    return month - 1, year


def _get_or_create_teacher(school):
    teacher, created = User.objects.get_or_create(
        email=TEACHER_EMAIL,
        defaults={
            'first_name': 'Alex',
            'last_name': 'Rivera',
            'user_type': 'teacher',
            'school': school,
            'is_active': True,
            'is_approved': True,
            'hourly_rate': Decimal('60.00'),
            'phone_number': '4161234567',
            'password': make_password(PASSWORD),
        }
    )
    if not created:
        teacher.school = school
        teacher.save(update_fields=['school'])
    return teacher, created


def _get_or_create_students(school, teacher):
    students = []
    for i, data in enumerate(STUDENT_DATA):
        email = STUDENT_EMAILS[i]
        student, created = User.objects.get_or_create(
            email=email,
            defaults={
                'first_name': data['first'],
                'last_name': data['last'],
                'user_type': 'student',
                'school': school,
                'is_active': True,
                'is_approved': True,
                'phone_number': f'416{700+i:07d}',
                'password': make_password(PASSWORD),
            }
        )
        if not created:
            student.school = school
            student.save(update_fields=['school'])

        # Ensure teacher assignment
        student.assigned_teachers.add(teacher)

        # Ensure BillableContact
        if not student.billable_contacts.filter(is_primary=True).exists():
            BillableContact.objects.create(
                student=student,
                school=school,
                contact_type='parent',
                first_name=data['parent_first'],
                last_name=data['last'],
                email=f'{data["parent_first"].lower()}.{data["last"].lower()}.parent{TEST_DOMAIN}',
                phone=f'905{600+i:07d}',
                street_address=TORONTO_STREETS[i % len(TORONTO_STREETS)],
                city=TORONTO_CITIES[i % len(TORONTO_CITIES)],
                province='ON',
                postal_code=TORONTO_POSTAL_CODES[i % len(TORONTO_POSTAL_CODES)],
                is_primary=True,
            )

        students.append((student, created))
    return students


def _create_or_replace_batch(teacher, school, month, year):
    """Create a fresh batch for the period, replacing any existing test batch."""
    existing = MonthlyInvoiceBatch.objects.filter(teacher=teacher, month=month, year=year).first()
    if existing:
        # Tear down all dependent objects before deleting
        _teardown_batch(existing, school, quiet=True)
        existing.delete()

    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher,
        school=school,
        month=month,
        year=year,
        status='draft',
    )


def _add_lessons(batch, students_list, month, year, default_status='completed'):
    """Add BatchLessonItems to the batch. Returns items grouped by student."""
    online_student_rate = Decimal('100.00')
    inperson_student_rate = Decimal('120.00')
    online_teacher_rate = Decimal('45.00')
    inperson_teacher_rate = batch.teacher.hourly_rate or Decimal('60.00')

    items_by_student = {}
    day = 5  # start from day 5 to avoid weekend/holiday edge cases

    for student in students_list:
        items = []
        for cfg in LESSON_CONFIGS:
            ltype = cfg['lesson_type']
            t_rate = online_teacher_rate if ltype == 'online' else inperson_teacher_rate
            s_rate = online_student_rate if ltype == 'online' else inperson_student_rate
            duration = Decimal(cfg['duration_min']) / Decimal('60')

            item = BatchLessonItem.objects.create(
                batch=batch,
                student=student,
                scheduled_date=datetime.date(year, month, min(day, 28)),
                start_time=random.choice(LESSON_START_TIMES),
                duration=duration,
                lesson_type=ltype,
                teacher_rate=t_rate,
                student_rate=s_rate,
                status=default_status,
                teacher_notes=random.choice(TEACHER_NOTES_POOL),
                is_one_off=True,
            )
            items.append(item)
            day = (day % 27) + 5  # cycle days

        items_by_student[student] = items

    # Bypass auto-trial: force all items to the intended default status
    batch.lesson_items.update(status=default_status)
    return items_by_student


def _approve_batch(batch, school, items_by_student, management_user):
    """
    Replicate batch approval logic: create Lessons, StudentInvoices, teacher Invoice.
    Returns (list[StudentInvoice], Invoice).
    """
    student_invoices = []

    with transaction.atomic():
        # Create Lesson + StudentInvoice for each student
        for student, batch_items in items_by_student.items():
            primary_contact = student.billable_contacts.get(is_primary=True)
            lesson_objs = []

            for item in batch_items:
                lesson = Lesson(
                    teacher=batch.teacher,
                    student=student,
                    school=school,
                    lesson_type=item.lesson_type,
                    is_trial=False,
                    scheduled_date=timezone.make_aware(
                        datetime.datetime.combine(item.scheduled_date, datetime.time.min)
                    ),
                    duration=item.duration,
                    teacher_rate=item.teacher_rate,
                    student_rate=item.student_rate,
                    status='confirmed',
                    teacher_notes=item.teacher_notes,
                )
                lesson._is_trial_explicitly_set = True
                lesson.save()
                item.created_lesson = lesson
                item.save(update_fields=['created_lesson'])
                lesson_objs.append(lesson)

            # StudentInvoice
            si = StudentInvoice(
                batch=batch,
                student=student,
                school=school,
                amount=Decimal('0.00'),
                billing_contact_name=f"{primary_contact.first_name} {primary_contact.last_name}",
                billing_email=primary_contact.email,
                billing_phone=primary_contact.phone,
                billing_street_address=primary_contact.street_address,
                billing_city=primary_contact.city,
                billing_province=primary_contact.province,
                billing_postal_code=primary_contact.postal_code,
            )
            si.save()
            si.lesson_items.set(batch_items)
            si.amount = si.calculate_amount()
            si.save()
            student_invoices.append(si)

        # Teacher Invoice (linked to batch via batch.invoice FK)
        teacher = batch.teacher
        all_lesson_objs = [
            item.created_lesson
            for items in items_by_student.values()
            for item in items
            if item.created_lesson
        ]
        teacher_invoice = Invoice(
            invoice_type='teacher_payment',
            teacher=teacher,
            school=school,
            status='pending',
            created_by=management_user,
            payment_balance=Decimal('0.00'),
            total_amount=Decimal('0.00'),
        )
        teacher_invoice.save()
        teacher_invoice.lessons.set(all_lesson_objs)
        # Let Invoice.save() recalculate from lessons
        teacher_invoice.save()

        # Link invoice to batch
        batch.invoice = teacher_invoice
        batch.status = 'approved'
        batch.reviewed_by = management_user
        batch.reviewed_at = timezone.now()
        batch.submitted_at = timezone.now()
        batch.save()

        # Populate credit fields on StudentInvoice (Phase 20 — no PreBillingInvoice = no credit)
        for si in student_invoices:
            si.credit_applied = Decimal('0.00')
            si.amount_after_credit = si.amount
            si.save(update_fields=['credit_applied', 'amount_after_credit'])

    return student_invoices, teacher_invoice


def _apply_credits(batch, student_invoices, school):
    """
    For each student: create a PreBillingInvoice with amount = 80% of actual invoice amount.
    This simulates a pre-payment credit leaving ~20% as the credit_applied amount.
    Updates StudentInvoice.credit_applied + amount_after_credit.
    """
    period_start, period_end = _month_range(batch.month, batch.year)
    updated = []

    for si in student_invoices:
        pre_amount = (si.amount * Decimal('0.80')).quantize(Decimal('0.01'))

        pre_inv, created = PreBillingInvoice.objects.get_or_create(
            student=si.student,
            school=school,
            period_start=period_start,
            period_end=period_end,
            defaults={
                'status': 'paid',
                'amount': pre_amount,
            },
        )
        if not created:
            pre_inv.amount = pre_amount
            pre_inv.status = 'paid'
            pre_inv.save(update_fields=['amount', 'status'])

        credit_applied = max(Decimal('0.00'), si.amount - pre_inv.amount)
        si.credit_applied = credit_applied
        si.amount_after_credit = pre_inv.amount
        si.save(update_fields=['credit_applied', 'amount_after_credit'])

        # Create/update StudentCreditAccount (subtract consumed credit)
        account, _ = StudentCreditAccount.objects.get_or_create(
            student=si.student,
            school=school,
            defaults={'balance': Decimal('0.00')},
        )
        updated.append((si, pre_inv))

    return updated


def _apply_expenses(batch, school, amount=Decimal('350.00'), notes='Studio rent + utilities'):
    """Create (or update) a SchoolMonthlyExpenses record for the batch period."""
    period_start, period_end = _month_range(batch.month, batch.year)
    record, _ = SchoolMonthlyExpenses.objects.update_or_create(
        school=school,
        period_start=period_start,
        period_end=period_end,
        defaults={'amount': amount, 'notes': notes},
    )
    return record


def _create_prebilling_sent(batch, students_list, school, month, year, items_by_student):
    """
    Create PreBillingInvoice(status='sent') for each student in the batch.
    Amount = sum of student charges for their batch items (pre-billing locks in the estimate).
    Returns list of created PreBillingInvoice instances.
    """
    period_start, period_end = _month_range(month, year)
    invoices = []
    for student in students_list:
        items = items_by_student.get(student, [])
        estimated_amount = sum(
            item.student_rate * item.duration for item in items
        ).quantize(Decimal('0.01'))

        pre_inv, _ = PreBillingInvoice.objects.update_or_create(
            student=student,
            school=school,
            period_start=period_start,
            period_end=period_end,
            defaults={
                'status': 'sent',
                'amount': estimated_amount,
            },
        )
        invoices.append(pre_inv)
    return invoices


def _mark_teacher_paid(teacher_invoice, month, year):
    """Mark a teacher invoice as paid with a realistic date and reference number."""
    last_day = calendar.monthrange(year, month)[1]
    teacher_invoice.status = 'paid'
    teacher_invoice.date_paid = datetime.date(year, month, last_day)
    teacher_invoice.reference_number = f'ETFR-{year}{month:02d}-TEST'
    teacher_invoice.save(update_fields=['status', 'date_paid', 'reference_number'])


def _teardown_batch(batch, school, quiet=False):
    """Delete all records associated with a single batch."""
    period_start, period_end = _month_range(batch.month, batch.year)

    # Student-level records
    for item in batch.lesson_items.all():
        if item.created_lesson:
            item.created_lesson.delete()

    # StudentInvoices (M2M cleared automatically on delete)
    student_ids = list(batch.student_invoices.values_list('student_id', flat=True))
    batch.student_invoices.all().delete()

    # PreBillingInvoices for these students in this period
    PreBillingInvoice.objects.filter(
        student_id__in=student_ids,
        school=school,
        period_start=period_start,
        period_end=period_end,
    ).delete()

    # SchoolMonthlyExpenses for this period
    SchoolMonthlyExpenses.objects.filter(
        school=school,
        period_start=period_start,
        period_end=period_end,
    ).delete()

    # Teacher invoice linked to batch
    if batch.invoice:
        inv = batch.invoice
        batch.invoice = None
        batch.save(update_fields=['invoice'])
        inv.delete()


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = (
        'Seed billing test data for dashboard UI testing. '
        'All test records use @maplekeytest.com emails and can be wiped with teardown_billing_test.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--month', type=int, default=None,
                            help='Month (1-12). Default: current month.')
        parser.add_argument('--year', type=int, default=None,
                            help='Year. Default: current year.')
        parser.add_argument('--status', type=str, default='approved',
                            choices=['draft', 'submitted', 'approved'],
                            help='Batch status to create. Default: approved.')
        parser.add_argument('--scenario', type=str, default='basic',
                            choices=['basic', 'full', 'multi', 'pre-billed'],
                            help=(
                                'basic: approved batch + student invoices + teacher invoice (pending). '
                                'full: basic + PreBillingInvoice credits + SchoolMonthlyExpenses + paid teacher invoice. '
                                'multi: 3 consecutive months of full data for period nav testing. '
                                'pre-billed: submitted batch + PreBillingInvoices in sent status (simulate billable contact paying before approval).'
                            ))
        parser.add_argument('--list', action='store_true',
                            help='List all existing test data and exit.')

    def handle(self, *args, **options):
        school = School.objects.first()
        if not school:
            self.stdout.write(self.style.ERROR('No School found. Create one via the admin first.'))
            return

        # --list flag: just show what exists
        if options['list']:
            self._list_test_data(school)
            return

        month = options['month'] or timezone.now().month
        year = options['year'] or timezone.now().year
        status = options['status']
        scenario = options['scenario']

        # Get management user for FK references
        mgmt = User.objects.filter(user_type='management', school=school).first()
        if not mgmt:
            self.stdout.write(self.style.ERROR('No management user found. Create one first.'))
            return

        # Ensure teacher + students exist
        teacher, t_new = _get_or_create_teacher(school)
        student_pairs = _get_or_create_students(school, teacher)
        students_list = [s for s, _ in student_pairs]

        if t_new:
            self.stdout.write(self.style.SUCCESS(f'  ✓ Created teacher: {TEACHER_EMAIL} / {PASSWORD}'))
        else:
            self.stdout.write(f'  ↺ Reusing teacher: {TEACHER_EMAIL}')

        for student, created in student_pairs:
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✓ Created student: {student.email}'))

        self.stdout.write('')

        # Determine which months to seed
        if scenario == 'multi':
            periods = []
            m, y = month, year
            for _ in range(3):
                periods.append((m, y))
                m, y = _prev_month(m, y)
            periods.reverse()  # oldest first
        else:
            periods = [(month, year)]

        for m, y in periods:
            self._seed_period(
                school=school,
                teacher=teacher,
                students_list=students_list,
                month=m,
                year=y,
                status=status if scenario != 'multi' else 'approved',
                scenario=scenario if scenario != 'multi' else 'full',
                mgmt=mgmt,
            )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('━' * 60))
        self.stdout.write(self.style.SUCCESS('  TEST DATA READY'))
        self.stdout.write(self.style.SUCCESS('━' * 60))
        self.stdout.write(f'  Management login:  localhost:5173  →  Management → Dashboard')
        self.stdout.write(f'  Teacher login:     {TEACHER_EMAIL}  /  {PASSWORD}')
        self.stdout.write(f'  Students:          {", ".join(s.get_full_name() for s in students_list)}')
        self.stdout.write(self.style.SUCCESS('━' * 60))
        self.stdout.write(f'  Wipe with:  docker compose exec api python manage.py teardown_billing_test')

    def _seed_period(self, school, teacher, students_list, month, year, status, scenario, mgmt):
        import calendar as _cal
        month_name = _cal.month_name[month]
        self.stdout.write(f'Seeding {month_name} {year} (scenario={scenario}, status={status})...')

        batch = _create_or_replace_batch(teacher, school, month, year)
        # Future months in draft use 'confirmed' — matches pre-billing UX (planned lessons).
        # Past/current months use 'completed' — lessons already happened.
        today = datetime.date.today()
        is_future_month = datetime.date(year, month, 1) > today.replace(day=1)
        lesson_status = 'confirmed' if (status == 'draft' and is_future_month) else 'completed'
        items_by_student = _add_lessons(batch, students_list, month, year, default_status=lesson_status)

        if status == 'draft':
            self.stdout.write(self.style.SUCCESS(f'  ✓ Draft batch: {batch.batch_number}'))
            return

        # Submitted
        batch.status = 'submitted'
        batch.submitted_at = timezone.now()
        batch.save(update_fields=['status', 'submitted_at'])

        if status == 'submitted' and scenario != 'pre-billed':
            self.stdout.write(self.style.SUCCESS(f'  ✓ Submitted batch: {batch.batch_number}'))
            return

        if scenario == 'pre-billed':
            # Submitted + PreBillingInvoices sent (but NOT approved yet)
            pre_invoices = _create_prebilling_sent(batch, students_list, school, month, year, items_by_student)
            total_prebilled = sum(pi.amount for pi in pre_invoices)
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✓ Submitted batch: {batch.batch_number} | '
                    f'{len(pre_invoices)} pre-billing invoices sent (${total_prebilled} total)'
                )
            )
            self.stdout.write(
                f'    → Students: {", ".join(s.get_full_name() for s in students_list)}'
            )
            self.stdout.write(
                f'    → Simulate payment: python manage.py teardown_billing_test --help'
                f' OR hit /api/billing/helcim/webhook/ with test payload'
            )
            return

        # Approved
        student_invoices, teacher_invoice = _approve_batch(batch, school, items_by_student, mgmt)
        total_student = sum(si.amount for si in student_invoices)
        total_teacher = teacher_invoice.total_amount

        self.stdout.write(
            self.style.SUCCESS(
                f'  ✓ Approved batch: {batch.batch_number} | '
                f'student total=${total_student} | teacher pay=${total_teacher}'
            )
        )

        if scenario == 'full':
            # Credits
            _apply_credits(batch, student_invoices, school)
            credit_totals = sum(si.credit_applied for si in StudentInvoice.objects.filter(batch=batch))
            self.stdout.write(self.style.SUCCESS(f'  ✓ Credits applied: ${credit_totals} total'))

            # Expenses
            exp = _apply_expenses(batch, school)
            self.stdout.write(self.style.SUCCESS(f'  ✓ Expenses: ${exp.amount} ({exp.notes})'))

            # Mark teacher paid
            _mark_teacher_paid(teacher_invoice, month, year)
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✓ Teacher invoice paid: {teacher_invoice.reference_number} on {teacher_invoice.date_paid}'
                )
            )

    def _list_test_data(self, school):
        self.stdout.write('\n=== EXISTING TEST DATA (@maplekeytest.com) ===\n')

        teachers = User.objects.filter(email__endswith=TEST_DOMAIN, user_type='teacher')
        if not teachers:
            self.stdout.write('  No test teachers found.')
            return

        for teacher in teachers:
            self.stdout.write(f'Teacher: {teacher.email}')
            batches = MonthlyInvoiceBatch.objects.filter(teacher=teacher).order_by('-year', '-month')
            for b in batches:
                si_count = b.student_invoices.count()
                inv_info = f'teacher_invoice={b.invoice}' if b.invoice else 'no teacher invoice'
                self.stdout.write(
                    f'  Batch {b.batch_number} ({b.month}/{b.year}) status={b.status} '
                    f'lessons={b.lesson_items.count()} student_invoices={si_count} {inv_info}'
                )

        students = User.objects.filter(email__endswith=TEST_DOMAIN, user_type='student')
        self.stdout.write(f'\nStudents: {students.count()}')
        for s in students:
            si_count = StudentInvoice.objects.filter(student=s).count()
            pre_count = PreBillingInvoice.objects.filter(student=s).count()
            self.stdout.write(f'  {s.email}: student_invoices={si_count} pre_billing={pre_count}')
