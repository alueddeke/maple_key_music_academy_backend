"""
Seed test data: Create a monthly invoice batch with lessons for a teacher.

Usage:
    python manage.py seed_batch_lessons --teacher-email=teacher@example.com --month=2 --year=2026
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from billing.models import User, Student, MonthlyInvoiceBatch, BatchLessonItem
import random
from datetime import datetime, timedelta


class Command(BaseCommand):
    help = 'Create test batch lessons for a teacher'

    def add_arguments(self, parser):
        parser.add_argument(
            '--teacher-email',
            type=str,
            required=True,
            help='Email of the teacher'
        )
        parser.add_argument(
            '--month',
            type=int,
            default=None,
            help='Month (1-12, default: current month)'
        )
        parser.add_argument(
            '--year',
            type=int,
            default=None,
            help='Year (default: current year)'
        )
        parser.add_argument(
            '--lessons-per-student',
            type=int,
            default=4,
            help='Number of lessons per student (default: 4)'
        )

    def handle(self, *args, **options):
        teacher_email = options['teacher_email']
        month = options['month'] or timezone.now().month
        year = options['year'] or timezone.now().year
        lessons_per_student = options['lessons_per_student']

        # Find teacher
        try:
            teacher = User.objects.get(email=teacher_email, user_type='teacher')
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Teacher not found: {teacher_email}'))
            return

        # Get teacher's students
        students = Student.objects.filter(assigned_teachers=teacher, is_active=True)

        if not students.exists():
            self.stdout.write(self.style.ERROR(f'No students assigned to teacher: {teacher.name}'))
            self.stdout.write('Run: python manage.py seed_teacher_students first')
            return

        self.stdout.write(f'Creating batch for {teacher.name} - {month}/{year}')
        self.stdout.write(f'Found {students.count()} students')

        # Create or get batch
        batch, created = MonthlyInvoiceBatch.objects.get_or_create(
            teacher=teacher,
            month=month,
            year=year,
            defaults={
                'status': 'draft',
            }
        )

        if not created:
            self.stdout.write(self.style.WARNING(f'Batch already exists: {batch.batch_number}'))
            # Clear existing lessons
            batch.lesson_items.all().delete()
            self.stdout.write('Cleared existing lessons')

        # Create lessons for each student
        lesson_count = 0
        lesson_types = ['online', 'in_person']

        # Get teacher's hourly rate (for in-person lessons)
        teacher_hourly_rate = Decimal(str(teacher.hourly_rate)) if teacher.hourly_rate else Decimal('50.00')
        online_teacher_rate = Decimal('45.00')  # Global online rate
        online_student_rate = Decimal('60.00')
        inperson_student_rate = Decimal('100.00')

        for student in students:
            # Create multiple lessons per student
            for lesson_num in range(lessons_per_student):
                # Random date within the month
                day = random.randint(1, 28)  # Safe for all months
                date = datetime(year, month, day)

                # Random time (between 9 AM and 7 PM)
                hour = random.randint(9, 18)
                minute = random.choice([0, 30])
                time = f'{hour:02d}:{minute:02d}:00'

                # Random lesson type and duration
                lesson_type = random.choice(lesson_types)
                duration = random.choice([30, 45, 60])

                # Calculate rates
                if lesson_type == 'online':
                    teacher_rate = online_teacher_rate
                    student_rate = online_student_rate
                else:
                    teacher_rate = teacher_hourly_rate
                    student_rate = inperson_student_rate

                # Calculate payment based on duration
                teacher_payment = (teacher_rate * Decimal(duration) / Decimal('60')).quantize(Decimal('0.01'))
                student_charge = (student_rate * Decimal(duration) / Decimal('60')).quantize(Decimal('0.01'))

                # Random status (mostly completed, some pending)
                status = random.choices(
                    ['completed', 'confirmed', 'cancelled'],
                    weights=[0.8, 0.15, 0.05]  # 80% completed, 15% confirmed, 5% cancelled
                )[0]

                # Create lesson item
                lesson = BatchLessonItem.objects.create(
                    batch=batch,
                    student=student,
                    scheduled_date=date.date(),
                    start_time=time,
                    duration=duration,
                    lesson_type=lesson_type,
                    teacher_rate=teacher_rate,
                    student_rate=student_rate,
                    teacher_payment=teacher_payment,
                    student_charge=student_charge,
                    status=status,
                    cancelled_by_type='teacher' if status == 'cancelled' else None,
                    cancellation_reason='Student was sick' if status == 'cancelled' else None,
                    teacher_notes=f'Lesson {lesson_num + 1} - Worked on scales' if random.random() > 0.5 else None,
                    is_one_off=False,
                )

                lesson_count += 1

        # Refresh batch to recalculate totals
        batch.refresh_from_db()

        self.stdout.write(self.style.SUCCESS(f'\n✅ Done! Created batch with {lesson_count} lessons'))
        self.stdout.write(f'Batch Number: {batch.batch_number}')
        self.stdout.write(f'Status: {batch.status}')
        self.stdout.write(f'Total Teacher Payment: ${batch.total_teacher_payment}')
        self.stdout.write(f'Total Student Charges: ${batch.total_student_charges}')
        self.stdout.write(f'\nView in UI: /invoice (login as {teacher_email})')
