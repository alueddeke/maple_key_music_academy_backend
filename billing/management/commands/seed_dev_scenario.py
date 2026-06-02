"""
Create a complete test scenario for local development.

Creates teacher + students (with billing contacts) + a submitted batch
ready to approve in one command. All user data is randomized and fully filled.

Usage:
    # Fastest — new teacher + 3 students + submitted batch for next available month
    docker compose exec api python manage.py seed_dev_scenario

    # Use an existing teacher, create fresh students + batch
    docker compose exec api python manage.py seed_dev_scenario --teacher-email=alex@example.com

    # Full control
    docker compose exec api python manage.py seed_dev_scenario \\
        --teacher-email=alex@example.com \\
        --month=8 --year=2026 \\
        --students=4 \\
        --status=submitted

    # Just create a management user (for fresh dev environments)
    docker compose exec api python manage.py seed_dev_scenario --management-only

Why this command exists
-----------------------
Teachers can only submit one batch per month (unique_together: teacher/month/year).
During dev/UAT it's often impossible to test the approve flow because both test
teachers have already submitted for the current month.

This command bypasses that by creating batches for future months, creating fresh
teachers, and — critically — using queryset .update() to set lesson status AFTER
creation so the BatchLessonItem.save() auto-trial logic doesn't fire.

Auto-trial logic (BatchLessonItem.save):
    If student has 0 prior Lesson records AND 0 prior BatchLessonItems at save time,
    status is forced to 'trial'. This command sets status='completed' via .update()
    after bulk creation to bypass this.

Billing contact requirement:
    The batch approval view blocks if any student in the batch has a BillableContact
    with missing street_address / city / province / postal_code. This command always
    creates fully-populated BillableContacts.
"""

import random
import string
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth.hashers import make_password

from billing.models import (
    User,
    School,
    MonthlyInvoiceBatch,
    BatchLessonItem,
    BillableContact,
)

# ---------------------------------------------------------------------------
# Fake data pools — randomized but realistic-looking
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    'Emma', 'Liam', 'Olivia', 'Noah', 'Ava', 'Ethan', 'Sophia', 'Mason',
    'Isabella', 'William', 'Mia', 'James', 'Charlotte', 'Benjamin', 'Amelia',
    'Lucas', 'Harper', 'Henry', 'Evelyn', 'Alexander',
]

LAST_NAMES = [
    'Chen', 'Williams', 'Patel', 'Thompson', 'Garcia', 'Kim', 'Brown',
    'Nguyen', 'Taylor', 'Singh', 'Lee', 'Anderson', 'Martinez', 'Wilson',
    'Davis', 'Miller', 'Moore', 'Jackson', 'White', 'Harris',
]

PARENT_FIRST_NAMES = [
    'Michael', 'Jennifer', 'David', 'Sarah', 'Robert', 'Michelle',
    'Christopher', 'Linda', 'Matthew', 'Patricia',
]

TORONTO_STREETS = [
    '123 Bloor St W', '456 Spadina Ave', '789 Queen St E',
    '321 King St W', '654 Yonge St', '987 Dundas St W',
    '147 College St', '258 Bathurst St', '369 Ossington Ave',
    '111 Roncesvalles Ave',
]

TORONTO_CITIES = ['Toronto', 'North York', 'Scarborough', 'Etobicoke', 'Mississauga']
TORONTO_POSTAL_CODES = ['M5V 1J2', 'M6G 3B4', 'M4K 2E6', 'M6P 1Z5', 'M5R 1Z1', 'L5B 3W8']

LESSON_START_TIMES = [
    datetime.time(9, 0), datetime.time(10, 0), datetime.time(11, 0),
    datetime.time(14, 0), datetime.time(15, 0), datetime.time(16, 0),
    datetime.time(17, 0), datetime.time(18, 0),
]

TEACHER_NOTES_POOL = [
    'Worked on C major scale — good progress.',
    'Reviewed sight-reading exercises from last week.',
    'Introduced chord progressions I-IV-V.',
    'Focused on hand positioning and posture.',
    'Practiced Für Elise — measures 1–20.',
    'Worked on rhythm exercises with metronome at 60 BPM.',
    'Introduced the concept of dynamics (piano/forte).',
    '',  # blank is fine
]


def _random_name():
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


def _random_email(first, last, suffix=''):
    tag = ''.join(random.choices(string.digits, k=4))
    domain = random.choice(['gmail.com', 'yahoo.ca', 'outlook.com', 'hotmail.com'])
    return f'{first.lower()}.{last.lower()}{suffix}{tag}@{domain}'


def _random_phone():
    area = random.choice(['416', '647', '905', '519'])
    return f'{area}{random.randint(1000000, 9999999)}'


def _random_postal():
    return random.choice(TORONTO_POSTAL_CODES)


def _next_available_month(teacher):
    """Find the next month for which this teacher has no existing batch."""
    now = timezone.now()
    month, year = now.month, now.year
    for _ in range(24):  # look up to 24 months ahead
        month += 1
        if month > 12:
            month = 1
            year += 1
        exists = MonthlyInvoiceBatch.objects.filter(
            teacher=teacher, month=month, year=year
        ).exists()
        if not exists:
            return month, year
    raise RuntimeError('Could not find a free month for this teacher in the next 2 years.')


class Command(BaseCommand):
    help = (
        'Create a complete dev test scenario: teacher + students + submitted batch. '
        'One command — everything fully populated and ready to approve in the UI.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--teacher-email',
            type=str,
            default=None,
            help='Use an existing teacher by email instead of creating a new one.',
        )
        parser.add_argument(
            '--month',
            type=int,
            default=None,
            help='Month for the batch (1-12). Default: next available month for the teacher.',
        )
        parser.add_argument(
            '--year',
            type=int,
            default=None,
            help='Year for the batch. Default: derived from --month logic.',
        )
        parser.add_argument(
            '--students',
            type=int,
            default=3,
            help='Number of new students to create (default: 3).',
        )
        parser.add_argument(
            '--lessons-per-student',
            type=int,
            default=3,
            help='Completed lessons per student in the batch (default: 3).',
        )
        parser.add_argument(
            '--status',
            type=str,
            default='submitted',
            choices=['draft', 'submitted'],
            help='Batch status (default: submitted — ready to approve).',
        )
        parser.add_argument(
            '--management-only',
            action='store_true',
            help='Only create a management user. Skip teacher/student/batch creation.',
        )
        parser.add_argument(
            '--password',
            type=str,
            default='testpass123',
            help='Password for all created users (default: testpass123).',
        )

    # ------------------------------------------------------------------
    # Main handler
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        school = School.objects.first()
        if not school:
            self.stdout.write(self.style.ERROR('No School found. Create one via the admin first.'))
            return

        password = options['password']

        if options['management_only']:
            mgmt_user = self._create_management_user(school, password)
            self.stdout.write(self.style.SUCCESS(f'\n✓ Management user: {mgmt_user.email} / {password}'))
            return

        # ---- Teacher ----
        if options['teacher_email']:
            try:
                teacher = User.objects.get(email=options['teacher_email'], user_type='teacher')
                self.stdout.write(f'Using existing teacher: {teacher.get_full_name()} <{teacher.email}>')
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Teacher not found: {options['teacher_email']}"))
                return
        else:
            teacher = self._create_teacher(school, password)
            self.stdout.write(self.style.SUCCESS(f'✓ Teacher: {teacher.get_full_name()} <{teacher.email}> / {password}'))

        # ---- Students ----
        students = []
        for _ in range(options['students']):
            student = self._create_student(school, teacher, password)
            students.append(student)
            self.stdout.write(
                self.style.SUCCESS(f'  ✓ Student: {student.get_full_name()} <{student.email}>')
            )

        # ---- Month / Year ----
        if options['month'] and options['year']:
            month, year = options['month'], options['year']
        elif options['month']:
            month, year = options['month'], timezone.now().year
        else:
            month, year = _next_available_month(teacher)
        self.stdout.write(f'\nBatch period: {month}/{year}')

        # ---- Batch ----
        batch = self._create_batch(
            teacher=teacher,
            school=school,
            students=students,
            month=month,
            year=year,
            lessons_per_student=options['lessons_per_student'],
            status=options['status'],
        )

        # ---- Summary ----
        items = batch.lesson_items.all()
        total_teacher = sum(i.calculate_teacher_payment() for i in items)
        total_student = sum(i.calculate_student_charge() for i in items)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('  DEV SCENARIO CREATED'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(f'  Batch:          {batch.batch_number}')
        self.stdout.write(f'  Period:         {month}/{year}')
        self.stdout.write(f'  Status:         {batch.status}')
        self.stdout.write(f'  Lessons:        {items.count()} ({items.filter(status="completed").count()} completed)')
        self.stdout.write(f'  Teacher payout: ${total_teacher}')
        self.stdout.write(f'  Student total:  ${total_student}')
        self.stdout.write('')
        self.stdout.write('  LOGIN AS MANAGEMENT to approve:')
        self.stdout.write('    http://localhost:5173/  →  Management → Batches')
        self.stdout.write('')
        self.stdout.write('  LOGIN AS TEACHER to view:')
        self.stdout.write(f'    email:    {teacher.email}')
        self.stdout.write(f'    password: {password}')
        self.stdout.write(self.style.SUCCESS('=' * 60))

    # ------------------------------------------------------------------
    # Creators
    # ------------------------------------------------------------------

    def _create_management_user(self, school, password):
        first, last = _random_name()
        email = _random_email(first, last, suffix='.mgmt')
        user = User.objects.create(
            email=email,
            first_name=first,
            last_name=last,
            user_type='management',
            school=school,
            is_active=True,
            is_approved=True,
            password=make_password(password),
        )
        return user

    def _create_teacher(self, school, password):
        first, last = _random_name()
        email = _random_email(first, last, suffix='.teacher')
        user = User.objects.create(
            email=email,
            first_name=first,
            last_name=last,
            user_type='teacher',
            school=school,
            is_active=True,
            is_approved=True,
            hourly_rate=Decimal(str(random.choice([50, 55, 60, 65]))),
            phone_number=_random_phone(),
            password=make_password(password),
        )
        return user

    def _create_student(self, school, teacher, password):
        first, last = _random_name()
        email = _random_email(first, last, suffix='.student')
        student = User.objects.create(
            email=email,
            first_name=first,
            last_name=last,
            user_type='student',
            school=school,
            is_active=True,
            is_approved=True,
            phone_number=_random_phone(),
            password=make_password(password),
        )
        student.assigned_teachers.add(teacher)

        # BillableContact — fully populated (required for batch approval)
        parent_first = random.choice(PARENT_FIRST_NAMES)
        BillableContact.objects.create(
            student=student,
            school=school,
            contact_type='parent',
            first_name=parent_first,
            last_name=last,
            email=_random_email(parent_first, last, suffix='.parent'),
            phone=_random_phone(),
            street_address=random.choice(TORONTO_STREETS),
            city=random.choice(TORONTO_CITIES),
            province='ON',
            postal_code=_random_postal(),
            is_primary=True,
        )
        return student

    def _create_batch(self, teacher, school, students, month, year, lessons_per_student, status):
        # Check for existing batch
        existing = MonthlyInvoiceBatch.objects.filter(
            teacher=teacher, month=month, year=year
        ).first()
        if existing:
            self.stdout.write(
                self.style.WARNING(
                    f'Batch {existing.batch_number} already exists for {month}/{year}. '
                    'Deleting existing lessons and replacing.'
                )
            )
            existing.lesson_items.all().delete()
            batch = existing
        else:
            batch = MonthlyInvoiceBatch.objects.create(
                teacher=teacher,
                school=school,
                month=month,
                year=year,
                status='draft',
            )

        # Create lesson items
        # IMPORTANT: BatchLessonItem.save() auto-sets status='trial' if the student
        # has no prior lessons. We create with status='completed' then use .update()
        # to bypass the save() hook. This is intentional — these are dev fixtures.
        online_teacher_rate = Decimal('45.00')
        online_student_rate = Decimal('100.00')
        inperson_teacher_rate = Decimal(str(teacher.hourly_rate or 50))
        inperson_student_rate = Decimal('120.00')

        for student in students:
            for lesson_num in range(lessons_per_student):
                day = random.randint(1, 28)
                lesson_type = random.choice(['online', 'in_person'])
                t_rate = online_teacher_rate if lesson_type == 'online' else inperson_teacher_rate
                s_rate = online_student_rate if lesson_type == 'online' else inperson_student_rate
                duration_min = random.choice([30, 45, 60])

                BatchLessonItem.objects.create(
                    batch=batch,
                    student=student,
                    scheduled_date=datetime.date(year, month, day),
                    start_time=random.choice(LESSON_START_TIMES),
                    duration=Decimal(duration_min) / Decimal('60'),
                    lesson_type=lesson_type,
                    teacher_rate=t_rate,
                    student_rate=s_rate,
                    # NOTE: save() may override this to 'trial' for students with no history.
                    # The .update() call below fixes this for all items in the batch.
                    status='completed',
                    teacher_notes=random.choice(TEACHER_NOTES_POOL),
                    is_one_off=True,
                )

        # Bypass auto-trial: force all items to 'completed' after creation
        # (save() fires per-object; .update() hits DB directly, skipping the hook)
        batch.lesson_items.update(status='completed')

        # Submit the batch if requested
        if status == 'submitted':
            batch.status = 'submitted'
            batch.submitted_at = timezone.now()
            batch.save(update_fields=['status', 'submitted_at'])

        return batch
