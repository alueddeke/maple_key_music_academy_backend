"""
Seed test data: Create students and assign them to a teacher.

Usage:
    python manage.py seed_teacher_students --teacher-email=teacher@example.com --count=10
"""
from django.core.management.base import BaseCommand
from billing.models import User, Student, BillableContact


class Command(BaseCommand):
    help = 'Create test students and assign to a teacher'

    def add_arguments(self, parser):
        parser.add_argument(
            '--teacher-email',
            type=str,
            required=True,
            help='Email of the teacher to assign students to'
        )
        parser.add_argument(
            '--count',
            type=int,
            default=5,
            help='Number of students to create (default: 5)'
        )

    def handle(self, *args, **options):
        teacher_email = options['teacher_email']
        count = options['count']

        # Find teacher
        try:
            teacher = User.objects.get(email=teacher_email, user_type='teacher')
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Teacher not found: {teacher_email}'))
            return

        self.stdout.write(f'Creating {count} students for teacher: {teacher.name}')

        first_names = ['Emma', 'Liam', 'Olivia', 'Noah', 'Ava', 'Ethan', 'Sophia', 'Mason', 'Isabella', 'William']
        last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez']

        created_students = []

        for i in range(count):
            first_name = first_names[i % len(first_names)]
            last_name = last_names[i % len(last_names)]
            email = f'{first_name.lower()}.{last_name.lower()}{i}@example.com'

            # Create student
            student, created = Student.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'phone_number': f'416-555-{str(i).zfill(4)}',
                    'is_active': True,
                }
            )

            if created:
                # Assign teacher
                student.assigned_teachers.add(teacher)

                # Create primary billable contact
                BillableContact.objects.create(
                    student=student,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone_number=f'416-555-{str(i).zfill(4)}',
                    contact_type='parent',
                    street_address=f'{100 + i} Main Street',
                    city='Toronto',
                    province='ON',
                    postal_code=f'M5H {i % 10}A{i % 10}',
                    is_primary=True,
                )

                created_students.append(student)
                self.stdout.write(self.style.SUCCESS(f'  ✓ Created: {student.first_name} {student.last_name}'))
            else:
                # Student already exists, just assign teacher
                if teacher not in student.assigned_teachers.all():
                    student.assigned_teachers.add(teacher)
                    self.stdout.write(self.style.WARNING(f'  ⚠ Already exists, assigned teacher: {student.first_name} {student.last_name}'))
                else:
                    self.stdout.write(self.style.WARNING(f'  ⚠ Already exists and assigned: {student.first_name} {student.last_name}'))

        self.stdout.write(self.style.SUCCESS(f'\n✅ Done! Created {len(created_students)} new students for {teacher.name}'))
        self.stdout.write(f'Total students assigned to teacher: {teacher.assigned_students.count()}')
