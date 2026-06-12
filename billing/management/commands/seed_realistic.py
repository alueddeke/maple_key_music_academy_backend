"""
Seed a realistic multi-teacher billing scenario for E2E Helcim testing.

Creates:
  - 5 teachers (3 at default $50/hr, 2 above at $65/$75)
  - 22 students spread across teachers (4-5 each), varied lesson frequency
  - May 2026: approved batches, all student invoices paid, teacher invoices paid
  - June 2026: approved batches, ~4 student invoices still 'sent', teacher invoices paid
  - July 2026: submitted batches (waiting management approval, no student invoices yet)
  - Recurring + one-off SchoolExpenseItems for May and June
  - All test data uses @maplekeytest.com domain (safe to teardown)

Usage:
    docker compose exec api python manage.py seed_realistic
    docker compose exec api python manage.py seed_realistic --dry-run
    docker compose exec api python manage.py seed_realistic --wipe-only
"""

import calendar
import datetime
import random
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from billing.models import (
    BatchLessonItem,
    BillableContact,
    Invoice,
    Lesson,
    MonthlyInvoiceBatch,
    PreBillingInvoice,
    School,
    SchoolExpenseItem,
    SchoolMonthlyExpenses,
    SchoolSettings,
    StudentCreditAccount,
    StudentInvoice,
    User,
    CreditTransaction,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_DOMAIN = '@maplekeytest.com'
PASSWORD = 'testpass123'

ONLINE_TEACHER_RATE = Decimal('45.00')
ONLINE_STUDENT_RATE = Decimal('60.00')
INPERSON_STUDENT_RATE = Decimal('100.00')

TEACHER_NOTES_POOL = [
    'Great progress on scales this week.',
    'Worked through chord inversions — student is improving quickly.',
    'Focused on sight-reading; introduced new piece.',
    'Reviewed hand positioning and dynamics.',
    'Practiced arpeggios and finger independence exercises.',
    'Student showed excellent rhythm today.',
    'Introduced music theory concepts alongside practical work.',
    'Worked on expression and phrasing.',
    '',
]

LESSON_START_TIMES = [
    datetime.time(9, 0), datetime.time(10, 0), datetime.time(11, 0),
    datetime.time(14, 0), datetime.time(15, 0), datetime.time(16, 0),
    datetime.time(17, 0), datetime.time(18, 0), datetime.time(19, 0),
]

# ---------------------------------------------------------------------------
# Teacher definitions
# ---------------------------------------------------------------------------

TEACHERS = [
    {
        'email': f'teacher.alex.rivera{TEST_DOMAIN}',
        'first': 'Alex', 'last': 'Rivera',
        'hourly_rate': Decimal('50.00'),
        'phone': '4161000001',
    },
    {
        'email': f'teacher.jordan.kim{TEST_DOMAIN}',
        'first': 'Jordan', 'last': 'Kim',
        'hourly_rate': Decimal('50.00'),
        'phone': '4161000002',
    },
    {
        'email': f'teacher.morgan.lee{TEST_DOMAIN}',
        'first': 'Morgan', 'last': 'Lee',
        'hourly_rate': Decimal('50.00'),
        'phone': '4161000003',
    },
    {
        'email': f'teacher.sam.patel{TEST_DOMAIN}',
        'first': 'Sam', 'last': 'Patel',
        'hourly_rate': Decimal('65.00'),
        'phone': '4161000004',
    },
    {
        'email': f'teacher.taylor.brooks{TEST_DOMAIN}',
        'first': 'Taylor', 'last': 'Brooks',
        'hourly_rate': Decimal('75.00'),
        'phone': '4161000005',
    },
]

# ---------------------------------------------------------------------------
# Student definitions per teacher
# Each lesson config: {'type': 'in_person'|'online', 'dur_min': int, 'count': int}
# count = number of lessons per month
# ---------------------------------------------------------------------------

TORONTO_STREETS = [
    '12 Bloor St W', '88 Spadina Ave', '204 Queen St E', '310 King St W',
    '501 Yonge St', '77 College St', '145 Danforth Ave', '66 St Clair Ave E',
    '230 Annette St', '14 Roncesvalles Ave', '502 Eglinton Ave W', '89 Ossington Ave',
    '321 Dupont St', '44 Harbord St', '178 Christie St', '90 Manning Ave',
    '403 Bathurst St', '67 Dovercourt Rd', '211 Avenue Rd', '35 Lippincott St',
    '100 St George St', '55 Madison Ave',
]

TORONTO_CITIES = ['Toronto', 'North York', 'Scarborough', 'Etobicoke', 'East York']
TORONTO_PROVINCES = ['ON'] * len(TORONTO_CITIES)
TORONTO_POSTAL_CODES = [
    'M5V 1J2', 'M6G 3B4', 'M4K 2E6', 'M6P 1Z5', 'M5R 1Z1',
    'M6H 2B5', 'M4M 1J4', 'M4T 1Z3', 'M6S 2V3', 'M6R 1H5',
    'M5P 1Z6', 'M6J 2M2', 'M6P 2E4', 'M5S 1K5', 'M6G 2M1',
    'M6K 2L7', 'M5T 2S3', 'M6H 3A2', 'M5R 2N4', 'M5T 1L7',
    'M5S 2E1', 'M5R 1N8',
]

# fmt: off
STUDENTS_BY_TEACHER_IDX = [
    # --- Alex Rivera ($50/hr) — 5 students ---
    [
        {
            'first': 'Sofia', 'last': 'Chen', 'parent_first': 'Wei', 'parent_last': 'Chen',
            'email': f'sofia.chen{TEST_DOMAIN}', 'phone': '9051000001',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Liam', 'last': 'Park', 'parent_first': 'Jin', 'parent_last': 'Park',
            'email': f'liam.park{TEST_DOMAIN}', 'phone': '9051000002',
            'lessons': [{'type': 'in_person', 'dur_min': 45, 'count': 4}],
        },
        {
            'first': 'Emma', 'last': 'Wilson', 'parent_first': 'James', 'parent_last': 'Wilson',
            'email': f'emma.wilson{TEST_DOMAIN}', 'phone': '9051000003',
            'lessons': [{'type': 'online', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Noah', 'last': 'Davis', 'parent_first': 'Sarah', 'parent_last': 'Davis',
            'email': f'noah.davis{TEST_DOMAIN}', 'phone': '9051000004',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 2}],
        },
        {
            'first': 'Olivia', 'last': 'Martinez', 'parent_first': 'Carlos', 'parent_last': 'Martinez',
            'email': f'olivia.martinez{TEST_DOMAIN}', 'phone': '9051000005',
            'lessons': [{'type': 'online', 'dur_min': 30, 'count': 8}],
        },
    ],
    # --- Jordan Kim ($50/hr) — 4 students ---
    [
        {
            'first': 'Ava', 'last': 'Thompson', 'parent_first': 'Linda', 'parent_last': 'Thompson',
            'email': f'ava.thompson{TEST_DOMAIN}', 'phone': '9051000006',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Lucas', 'last': 'Brown', 'parent_first': 'Mark', 'parent_last': 'Brown',
            'email': f'lucas.brown{TEST_DOMAIN}', 'phone': '9051000007',
            'lessons': [{'type': 'in_person', 'dur_min': 45, 'count': 4}],
        },
        {
            'first': 'Mia', 'last': 'Garcia', 'parent_first': 'Rosa', 'parent_last': 'Garcia',
            'email': f'mia.garcia{TEST_DOMAIN}', 'phone': '9051000008',
            'lessons': [{'type': 'online', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Ethan', 'last': 'White', 'parent_first': 'Tom', 'parent_last': 'White',
            'email': f'ethan.white{TEST_DOMAIN}', 'phone': '9051000009',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 2}],
        },
    ],
    # --- Morgan Lee ($50/hr) — 4 students ---
    [
        {
            'first': 'Isabella', 'last': 'Jones', 'parent_first': 'Patricia', 'parent_last': 'Jones',
            'email': f'isabella.jones{TEST_DOMAIN}', 'phone': '9051000010',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Jackson', 'last': 'Taylor', 'parent_first': 'David', 'parent_last': 'Taylor',
            'email': f'jackson.taylor{TEST_DOMAIN}', 'phone': '9051000011',
            'lessons': [{'type': 'online', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Charlotte', 'last': 'Anderson', 'parent_first': 'Susan', 'parent_last': 'Anderson',
            'email': f'charlotte.anderson{TEST_DOMAIN}', 'phone': '9051000012',
            'lessons': [{'type': 'in_person', 'dur_min': 45, 'count': 4}],
        },
        {
            'first': 'Aiden', 'last': 'Thomas', 'parent_first': 'Michael', 'parent_last': 'Thomas',
            'email': f'aiden.thomas{TEST_DOMAIN}', 'phone': '9051000013',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 2}],
        },
    ],
    # --- Sam Patel ($65/hr) — 5 students ---
    [
        {
            'first': 'Harper', 'last': 'Jackson', 'parent_first': 'Nicole', 'parent_last': 'Jackson',
            'email': f'harper.jackson{TEST_DOMAIN}', 'phone': '9051000014',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Evelyn', 'last': 'Harris', 'parent_first': 'Karen', 'parent_last': 'Harris',
            'email': f'evelyn.harris{TEST_DOMAIN}', 'phone': '9051000015',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Sebastian', 'last': 'Martin', 'parent_first': 'Luis', 'parent_last': 'Martin',
            'email': f'sebastian.martin{TEST_DOMAIN}', 'phone': '9051000016',
            'lessons': [{'type': 'in_person', 'dur_min': 45, 'count': 4}],
        },
        {
            'first': 'Grace', 'last': 'Lee', 'parent_first': 'Anne', 'parent_last': 'Lee',
            'email': f'grace.lee{TEST_DOMAIN}', 'phone': '9051000017',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 2}],
        },
        {
            'first': 'Luke', 'last': 'Walker', 'parent_first': 'Brian', 'parent_last': 'Walker',
            'email': f'luke.walker{TEST_DOMAIN}', 'phone': '9051000018',
            'lessons': [{'type': 'online', 'dur_min': 60, 'count': 4}],
        },
    ],
    # --- Taylor Brooks ($75/hr) — 4 students ---
    [
        {
            'first': 'Chloe', 'last': 'Hall', 'parent_first': 'Sandra', 'parent_last': 'Hall',
            'email': f'chloe.hall{TEST_DOMAIN}', 'phone': '9051000019',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Madison', 'last': 'Allen', 'parent_first': 'Rebecca', 'parent_last': 'Allen',
            'email': f'madison.allen{TEST_DOMAIN}', 'phone': '9051000020',
            'lessons': [{'type': 'in_person', 'dur_min': 60, 'count': 4}],
        },
        {
            'first': 'Ryan', 'last': 'Young', 'parent_first': 'Christopher', 'parent_last': 'Young',
            'email': f'ryan.young{TEST_DOMAIN}', 'phone': '9051000021',
            'lessons': [{'type': 'in_person', 'dur_min': 45, 'count': 4}],
        },
        {
            'first': 'Zoe', 'last': 'Hernandez', 'parent_first': 'Elena', 'parent_last': 'Hernandez',
            'email': f'zoe.hernandez{TEST_DOMAIN}', 'phone': '9051000022',
            'lessons': [{'type': 'online', 'dur_min': 60, 'count': 2}],
        },
    ],
]
# fmt: on

# Students that should stay 'sent' (not paid) for June — simulates waiting on payment
JUNE_SENT_EMAILS = {
    f'olivia.martinez{TEST_DOMAIN}',
    f'ethan.white{TEST_DOMAIN}',
    f'aiden.thomas{TEST_DOMAIN}',
    f'zoe.hernandez{TEST_DOMAIN}',
}

# ---------------------------------------------------------------------------
# Expense definitions
# ---------------------------------------------------------------------------

RECURRING_EXPENSES = [
    {'title': 'Management Payroll', 'amount': Decimal('600.00'), 'notes': 'Admin staff monthly payroll'},
    {'title': 'DigitalOcean Droplet', 'amount': Decimal('48.00'), 'notes': 'App server hosting (s-2vcpu-4gb)'},
    {'title': 'Domain Registration', 'amount': Decimal('12.00'), 'notes': 'maplekeymusic.academy — amortized monthly'},
    {'title': 'Claude Code', 'amount': Decimal('20.00'), 'notes': 'Anthropic Claude Code subscription'},
    {'title': 'Google Workspace', 'amount': Decimal('12.00'), 'notes': 'Business email and Drive'},
    {'title': 'Advertising', 'amount': Decimal('150.00'), 'notes': 'Meta + Google ads — student acquisition'},
]

ONE_OFF_EXPENSES = {
    5: [  # May
        {'title': 'Music Theory Workbooks', 'amount': Decimal('95.00'), 'notes': 'Student supply kits for new enrolments'},
    ],
    6: [  # June
        {'title': 'Studio Piano Tuning', 'amount': Decimal('175.00'), 'notes': 'Semi-annual tuning — studio piano'},
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_range(month, year):
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, 1), datetime.date(year, month, last)


def _wipe_test_data(school, stdout, style):
    """Delete all @maplekeytest.com records in dependency order."""
    test_teachers = list(User.objects.filter(email__endswith=TEST_DOMAIN, user_type='teacher'))
    test_students = list(User.objects.filter(email__endswith=TEST_DOMAIN, user_type='student'))

    if not test_teachers and not test_students:
        stdout.write('  No existing test data found.')
        return

    teacher_ids = [t.id for t in test_teachers]
    student_ids = [s.id for s in test_students]
    batches = MonthlyInvoiceBatch.objects.filter(teacher_id__in=teacher_ids)
    batch_ids = list(batches.values_list('id', flat=True))

    CreditTransaction.objects.filter(account__student_id__in=student_ids).delete()
    StudentCreditAccount.objects.filter(student_id__in=student_ids).delete()
    PreBillingInvoice.objects.filter(student_id__in=student_ids).delete()
    StudentInvoice.objects.filter(batch_id__in=batch_ids).delete()
    BatchLessonItem.objects.filter(batch_id__in=batch_ids).update(created_lesson=None)
    Lesson.objects.filter(teacher_id__in=teacher_ids).delete()
    MonthlyInvoiceBatch.objects.filter(id__in=batch_ids).update(invoice=None)
    Invoice.objects.filter(teacher_id__in=teacher_ids).delete()
    MonthlyInvoiceBatch.objects.filter(id__in=batch_ids).delete()

    # Expense items for any periods that only have test data
    batch_periods = set()
    for t_id in teacher_ids:
        for b in MonthlyInvoiceBatch.objects.filter(teacher_id=t_id):
            batch_periods.add((b.month, b.year))

    # Also clean expense items for May/June/July 2026 if exclusively test data
    for month, year in [(5, 2026), (6, 2026), (7, 2026)]:
        period_start, period_end = _month_range(month, year)
        non_test = MonthlyInvoiceBatch.objects.filter(
            school=school, month=month, year=year, status='approved'
        ).exclude(teacher_id__in=teacher_ids).exists()
        if not non_test:
            SchoolExpenseItem.objects.filter(
                school=school, period_start=period_start, period_end=period_end
            ).delete()
            SchoolMonthlyExpenses.objects.filter(
                school=school, period_start=period_start, period_end=period_end
            ).delete()

    BillableContact.objects.filter(student_id__in=student_ids).delete()
    User.objects.filter(id__in=student_ids).delete()
    User.objects.filter(id__in=teacher_ids).delete()

    stdout.write(style.SUCCESS(
        f'  ✓ Wiped {len(test_teachers)} teacher(s) and {len(test_students)} student(s).'
    ))


def _addr(idx):
    n = len(TORONTO_STREETS)
    return {
        'street_address': TORONTO_STREETS[idx % n],
        'city': TORONTO_CITIES[idx % len(TORONTO_CITIES)],
        'province': 'ON',
        'postal_code': TORONTO_POSTAL_CODES[idx % len(TORONTO_POSTAL_CODES)],
    }


def _create_teachers(school):
    teachers = []
    for t in TEACHERS:
        user, _ = User.objects.get_or_create(
            email=t['email'],
            defaults={
                'first_name': t['first'],
                'last_name': t['last'],
                'user_type': 'teacher',
                'school': school,
                'is_active': True,
                'is_approved': True,
                'hourly_rate': t['hourly_rate'],
                'phone_number': t['phone'],
                'password': make_password(PASSWORD),
            },
        )
        user.school = school
        user.hourly_rate = t['hourly_rate']
        user.save(update_fields=['school', 'hourly_rate'])
        teachers.append(user)
    return teachers


def _create_students(school, teachers, addr_offset):
    """Create all students, assign to teachers, create BillableContacts. Returns flat list."""
    all_students = []
    for t_idx, teacher in enumerate(teachers):
        for s_data in STUDENTS_BY_TEACHER_IDX[t_idx]:
            student, _ = User.objects.get_or_create(
                email=s_data['email'],
                defaults={
                    'first_name': s_data['first'],
                    'last_name': s_data['last'],
                    'user_type': 'student',
                    'school': school,
                    'is_active': True,
                    'is_approved': True,
                    'phone_number': s_data['phone'],
                    'password': make_password(PASSWORD),
                },
            )
            student.school = school
            student.save(update_fields=['school'])
            student.assigned_teachers.add(teacher)

            if not student.billable_contacts.filter(is_primary=True).exists():
                addr = _addr(addr_offset)
                BillableContact.objects.create(
                    student=student,
                    school=school,
                    contact_type='parent',
                    first_name=s_data['parent_first'],
                    last_name=s_data['parent_last'],
                    email=f"{s_data['parent_first'].lower()}.{s_data['parent_last'].lower()}.parent{TEST_DOMAIN}",
                    phone=s_data['phone'],
                    **addr,
                    is_primary=True,
                )
                addr_offset += 1

            all_students.append((teacher, student, s_data['lessons']))
    return all_students


def _lesson_dates(month, year, count, base_day):
    """Return `count` lesson dates spread through the month starting around base_day."""
    last = calendar.monthrange(year, month)[1]
    if count <= 4:
        # weekly: every 7 days
        days = [min(base_day + i * 7, last) for i in range(count)]
    else:
        # 2x/week: every 3-4 days
        days = [min(base_day + i * 3, last) for i in range(count)]
    return [datetime.date(year, month, d) for d in days]


def _build_lesson_items(batch, teacher, student, lesson_configs, month, year, day_offset):
    """Create BatchLessonItems. Returns list of items and next day_offset."""
    items = []
    for cfg in lesson_configs:
        ltype = cfg['type']
        dur = Decimal(cfg['dur_min']) / Decimal('60')
        t_rate = ONLINE_TEACHER_RATE if ltype == 'online' else teacher.hourly_rate
        s_rate = ONLINE_STUDENT_RATE if ltype == 'online' else INPERSON_STUDENT_RATE

        dates = _lesson_dates(month, year, cfg['count'], day_offset % 25 + 1)
        for d in dates:
            item = BatchLessonItem.objects.create(
                batch=batch,
                student=student,
                scheduled_date=d,
                start_time=random.choice(LESSON_START_TIMES),
                duration=dur,
                lesson_type=ltype,
                teacher_rate=t_rate,
                student_rate=s_rate,
                status='completed',
                teacher_notes=random.choice(TEACHER_NOTES_POOL),
                is_one_off=True,
            )
            items.append(item)
        day_offset += 3

    return items, day_offset


def _approve_batch(batch, school, items_by_student, mgmt):
    """Replicate approval: create Lessons, StudentInvoices, teacher Invoice."""
    student_invoices = []

    with transaction.atomic():
        for student, batch_items in items_by_student.items():
            contact = student.billable_contacts.get(is_primary=True)
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

            si = StudentInvoice(
                batch=batch,
                student=student,
                school=school,
                amount=Decimal('0.00'),
                billing_contact_name=f"{contact.first_name} {contact.last_name}",
                billing_email=contact.email,
                billing_phone=contact.phone,
                billing_street_address=contact.street_address,
                billing_city=contact.city,
                billing_province=contact.province,
                billing_postal_code=contact.postal_code,
            )
            si.save()
            si.lesson_items.set(batch_items)
            si.amount = si.calculate_amount()
            si.save()
            si.credit_applied = Decimal('0.00')
            si.amount_after_credit = si.amount
            si.save(update_fields=['credit_applied', 'amount_after_credit'])
            student_invoices.append(si)

        # Teacher invoice
        all_lessons = [
            item.created_lesson
            for items in items_by_student.values()
            for item in items
            if item.created_lesson
        ]
        teacher_invoice = Invoice(
            invoice_type='teacher_payment',
            teacher=batch.teacher,
            school=school,
            status='pending',
            created_by=mgmt,
            payment_balance=Decimal('0.00'),
            total_amount=Decimal('0.00'),
        )
        teacher_invoice.save()
        teacher_invoice.lessons.set(all_lessons)
        teacher_invoice.save()

        batch.invoice = teacher_invoice
        batch.status = 'approved'
        batch.reviewed_by = mgmt
        batch.reviewed_at = timezone.now()
        batch.submitted_at = timezone.now()
        batch.save()

    return student_invoices, teacher_invoice


def _make_prebilling(student, school, period_start, period_end, amount, status):
    pre, _ = PreBillingInvoice.objects.update_or_create(
        student=student,
        school=school,
        period_start=period_start,
        period_end=period_end,
        defaults={'amount': amount, 'status': status},
    )
    return pre


def _mark_teacher_paid(invoice, month, year):
    last = calendar.monthrange(year, month)[1]
    invoice.status = 'paid'
    invoice.date_paid = datetime.date(year, month, last)
    invoice.reference_number = f'ETFR-{year}{month:02d}-TEST'
    invoice.save(update_fields=['status', 'date_paid', 'reference_number'])


def _seed_expenses(school, month, year, is_recurring_first_period=False):
    """Create SchoolExpenseItems for the period. Returns (period_start, total_amount)."""
    period_start, period_end = _month_range(month, year)

    for exp in RECURRING_EXPENSES:
        SchoolExpenseItem.objects.create(
            school=school,
            period_start=period_start,
            period_end=period_end,
            title=exp['title'],
            amount=exp['amount'],
            notes=exp['notes'],
            is_recurring=True,
        )

    for exp in ONE_OFF_EXPENSES.get(month, []):
        SchoolExpenseItem.objects.create(
            school=school,
            period_start=period_start,
            period_end=period_end,
            title=exp['title'],
            amount=exp['amount'],
            notes=exp['notes'],
            is_recurring=False,
        )


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Seed realistic multi-teacher billing data for E2E testing.'

    def add_arguments(self, parser):
        parser.add_argument('--wipe-only', action='store_true', help='Wipe test data and exit.')
        parser.add_argument('--dry-run', action='store_true', help='Describe what would be created without touching the DB.')

    def handle(self, *args, **options):
        school = School.objects.first()
        if not school:
            self.stdout.write(self.style.ERROR('No School found. Create one first.'))
            return

        mgmt = User.objects.filter(user_type='management', school=school).first()
        if not mgmt:
            self.stdout.write(self.style.ERROR('No management user found. Create one first.'))
            return

        if options['dry_run']:
            self._print_preview()
            return

        self.stdout.write(self.style.WARNING('Wiping existing test data…'))
        _wipe_test_data(school, self.stdout, self.style)

        if options['wipe_only']:
            return

        self.stdout.write(self.style.WARNING('\nCreating teachers…'))
        teachers = _create_teachers(school)
        for t in teachers:
            self.stdout.write(f'  ✓ {t.get_full_name()} ({t.email}) — ${t.hourly_rate}/hr')

        self.stdout.write(self.style.WARNING('\nCreating students…'))
        all_records = _create_students(school, teachers, addr_offset=0)
        for _, student, _ in all_records:
            self.stdout.write(f'  ✓ {student.get_full_name()} ({student.email})')
        self.stdout.write(f'  → {len(all_records)} students total')

        # Seed May and June as approved completed periods
        for month, year in [(5, 2026), (6, 2026)]:
            self._seed_approved_period(school, teachers, all_records, month, year, mgmt)

        # Seed July as draft — teachers submit as Step 1 of E2E flow
        self._seed_draft_period(school, teachers, all_records, 7, 2026)

        self._print_summary(all_records)

    def _seed_approved_period(self, school, teachers, all_records, month, year, mgmt):
        import calendar as _cal
        self.stdout.write(self.style.WARNING(f'\nSeeding {_cal.month_name[month]} {year} (approved)…'))
        period_start, period_end = _month_range(month, year)

        total_student_revenue = Decimal('0.00')
        total_teacher_pay = Decimal('0.00')

        for teacher in teachers:
            # Collect this teacher's students + lesson configs
            teacher_records = [(s, cfgs) for (t, s, cfgs) in all_records if t.id == teacher.id]

            batch = MonthlyInvoiceBatch.objects.create(
                teacher=teacher,
                school=school,
                month=month,
                year=year,
                status='draft',
            )

            items_by_student = {}
            day_offset = 1
            for student, lesson_cfgs in teacher_records:
                items, day_offset = _build_lesson_items(
                    batch, teacher, student, lesson_cfgs, month, year, day_offset
                )
                items_by_student[student] = items

            # Force all items to completed — bypasses the first-lesson trial auto-set in save()
            batch.lesson_items.update(status='completed')

            student_invoices, teacher_invoice = _approve_batch(batch, school, items_by_student, mgmt)

            # Pre-billing invoices
            for si in student_invoices:
                status = 'paid' if (month == 5 or si.student.email not in JUNE_SENT_EMAILS) else 'sent'
                _make_prebilling(si.student, school, period_start, period_end, si.amount, status)
                if status == 'paid':
                    si.credit_applied = Decimal('0.00')
                    si.amount_after_credit = si.amount
                    si.save(update_fields=['credit_applied', 'amount_after_credit'])

            _mark_teacher_paid(teacher_invoice, month, year)
            total_student_revenue += sum(si.amount for si in student_invoices)
            total_teacher_pay += teacher_invoice.total_amount or Decimal('0.00')
            self.stdout.write(
                f'  ✓ {teacher.get_full_name()} — batch {batch.batch_number} '
                f'({len(student_invoices)} invoices)'
            )

        _seed_expenses(school, month, year)
        expense_total = sum(e['amount'] for e in RECURRING_EXPENSES) + sum(
            e['amount'] for e in ONE_OFF_EXPENSES.get(month, [])
        )
        self.stdout.write(
            f'  → Revenue: ${total_student_revenue:,.2f} | '
            f'Expenses: ${expense_total:,.2f} | '
            f'Teacher pay: ${total_teacher_pay:,.2f} | '
            f'Net: ${total_student_revenue - expense_total - total_teacher_pay:,.2f}'
        )

    def _seed_draft_period(self, school, teachers, all_records, month, year):
        """Seed draft batches for a future month. Lessons default to 'confirmed' (not yet happened)."""
        import calendar as _cal
        self.stdout.write(self.style.WARNING(f'\nSeeding {_cal.month_name[month]} {year} (draft — ready for teacher submission)…'))

        for teacher in teachers:
            teacher_records = [(s, cfgs) for (t, s, cfgs) in all_records if t.id == teacher.id]

            batch = MonthlyInvoiceBatch.objects.create(
                teacher=teacher,
                school=school,
                month=month,
                year=year,
                status='draft',
            )

            day_offset = 1
            for student, lesson_cfgs in teacher_records:
                _build_lesson_items(batch, teacher, student, lesson_cfgs, month, year, day_offset)
                day_offset += len(lesson_cfgs) * 3

            # Future month: lessons are planned/confirmed, not yet completed
            batch.lesson_items.update(status='confirmed')

            self.stdout.write(f'  ✓ {teacher.get_full_name()} — batch {batch.batch_number} (draft, confirmed lessons)')

    def _seed_submitted_period(self, school, teachers, all_records, month, year):
        import calendar as _cal
        self.stdout.write(self.style.WARNING(f'\nSeeding {_cal.month_name[month]} {year} (submitted — awaiting approval)…'))

        for teacher in teachers:
            teacher_records = [(s, cfgs) for (t, s, cfgs) in all_records if t.id == teacher.id]

            batch = MonthlyInvoiceBatch.objects.create(
                teacher=teacher,
                school=school,
                month=month,
                year=year,
                status='draft',
            )

            day_offset = 1
            for student, lesson_cfgs in teacher_records:
                _build_lesson_items(batch, teacher, student, lesson_cfgs, month, year, day_offset)
                day_offset += len(lesson_cfgs) * 3

            batch.lesson_items.update(status='completed')
            batch.status = 'submitted'
            batch.submitted_at = timezone.now()
            batch.save(update_fields=['status', 'submitted_at'])

            self.stdout.write(f'  ✓ {teacher.get_full_name()} — batch {batch.batch_number} (submitted)')

    def _print_preview(self):
        total_students = sum(len(g) for g in STUDENTS_BY_TEACHER_IDX)
        recurring_total = sum(e['amount'] for e in RECURRING_EXPENSES)
        self.stdout.write('\n── DRY RUN ─────────────────────────────────────────')
        self.stdout.write(f'Teachers : {len(TEACHERS)}')
        self.stdout.write(f'Students : {total_students}')
        self.stdout.write(f'Periods  : May 2026 (approved), June 2026 (approved), July 2026 (draft)')
        self.stdout.write(f'Recurring expenses/month: ${recurring_total}')
        for t_idx, t in enumerate(TEACHERS):
            students = STUDENTS_BY_TEACHER_IDX[t_idx]
            self.stdout.write(f"  {t['first']} {t['last']} (${t['hourly_rate']}/hr) — {len(students)} students")
        self.stdout.write('────────────────────────────────────────────────────\n')

    def _print_summary(self, all_records):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('━' * 64))
        self.stdout.write(self.style.SUCCESS('  REALISTIC TEST DATA READY'))
        self.stdout.write(self.style.SUCCESS('━' * 64))
        self.stdout.write(f'  Periods : May 2026 ✓ paid | June 2026 ✓ mixed | July 2026 📋 draft')
        self.stdout.write(f'  Teachers: {", ".join(t["email"] for t in TEACHERS)}')
        self.stdout.write(f'  Password: {PASSWORD}')
        self.stdout.write(f'  Students: {len(all_records)} total (22)')
        self.stdout.write(f'  June pending (sent): {", ".join(sorted(JUNE_SENT_EMAILS))}')
        self.stdout.write(self.style.SUCCESS('━' * 64))
        self.stdout.write(f'  Wipe: docker compose exec api python manage.py teardown_billing_test')
