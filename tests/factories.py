"""
Factory Boy factories for Maple Key Music Academy API testing

These factories generate realistic test data that matches the OpenAPI schemas
and business logic requirements.
"""

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from billing.models import Lesson, Invoice

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    """Factory for creating User instances"""
    
    class Meta:
        model = User
    
    email = factory.Sequence(lambda n: f'user{n}@example.com')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    user_type = 'teacher'
    is_approved = True
    phone_number = factory.Faker('phone_number')
    address = factory.Faker('address')
    bio = factory.Faker('text', max_nb_chars=200)
    instruments = factory.Faker('random_element', elements=[
        'Piano', 'Guitar', 'Violin', 'Drums', 'Voice', 'Piano, Guitar'
    ])
    hourly_rate = factory.Faker('pydecimal', left_digits=3, right_digits=2, positive=True, min_value=50, max_value=100)
    
    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        if not create:
            return
        password = extracted or 'password123'
        obj.set_password(password)
        obj.save()


class ManagementUserFactory(UserFactory):
    """Factory for creating management users"""
    user_type = 'management'
    is_approved = True
    bio = 'Music school administrator'
    instruments = ''
    hourly_rate = Decimal('0.00')


class TeacherUserFactory(UserFactory):
    """Factory for creating teacher users"""
    user_type = 'teacher'
    is_approved = True
    bio = factory.Faker('text', max_nb_chars=200)
    instruments = factory.Faker('random_element', elements=[
        'Piano', 'Guitar', 'Violin', 'Drums', 'Voice', 'Piano, Guitar', 'Piano, Voice'
    ])
    hourly_rate = factory.Faker('pydecimal', left_digits=3, right_digits=2, positive=True, min_value=60, max_value=90)


class StudentUserFactory(UserFactory):
    """Factory for creating student users"""
    user_type = 'student'
    is_approved = True
    bio = ''
    instruments = ''
    hourly_rate = Decimal('0.00')
    parent_email = factory.Faker('email')
    parent_phone = factory.Faker('phone_number')


class UnapprovedTeacherFactory(TeacherUserFactory):
    """Factory for creating unapproved teacher users"""
    is_approved = False


class LessonFactory(factory.django.DjangoModelFactory):
    """Factory for creating Lesson instances"""
    
    class Meta:
        model = Lesson
    
    teacher = factory.SubFactory(TeacherUserFactory)
    student = factory.SubFactory(StudentUserFactory)
    rate = factory.Faker('pydecimal', left_digits=3, right_digits=2, positive=True, min_value=50, max_value=100)
    scheduled_date = factory.Faker('date_time_between', start_date='-30d', end_date='+30d', tzinfo=timezone.utc)
    duration = factory.Faker('pydecimal', left_digits=1, right_digits=1, positive=True, min_value=0.5, max_value=2.0)
    status = factory.Faker('random_element', elements=['requested', 'confirmed', 'completed'])
    teacher_notes = factory.Faker('text', max_nb_chars=100)
    student_notes = factory.Faker('text', max_nb_chars=100)
    
    @factory.post_generation
    def set_completed_date(obj, create, extracted, **kwargs):
        if not create:
            return
        if obj.status == 'completed':
            obj.completed_date = timezone.now()
            obj.save()


class CompletedLessonFactory(LessonFactory):
    """Factory for creating completed lessons"""
    status = 'completed'
    completed_date = factory.LazyFunction(timezone.now)
    teacher_notes = factory.Faker('text', max_nb_chars=100)


class InvoiceFactory(factory.django.DjangoModelFactory):
    """Factory for creating Invoice instances"""
    
    class Meta:
        model = Invoice
    
    invoice_type = 'teacher_payment'
    teacher = factory.SubFactory(TeacherUserFactory)
    status = factory.Faker('random_element', elements=['draft', 'pending', 'approved'])
    payment_balance = factory.Faker('pydecimal', left_digits=4, right_digits=2, positive=True, min_value=100, max_value=1000)
    created_by = factory.SubFactory(TeacherUserFactory)
    
    @factory.post_generation
    def lessons(obj, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            obj.lessons.set(extracted)
        else:
            # Create some completed lessons for the invoice
            lessons = CompletedLessonFactory.create_batch(3, teacher=obj.teacher)
            obj.lessons.set(lessons)
            obj.payment_balance = obj.calculate_payment_balance()
            obj.save()


class PendingInvoiceFactory(InvoiceFactory):
    """Factory for creating pending invoices"""
    status = 'pending'


class ApprovedInvoiceFactory(InvoiceFactory):
    """Factory for creating approved invoices"""
    status = 'approved'
    approved_by = factory.SubFactory(ManagementUserFactory)
    approved_at = factory.LazyFunction(timezone.now)


# Complex scenario factories for integration testing
class TeacherWithLessonsFactory(factory.django.DjangoModelFactory):
    """Factory for creating a teacher with completed lessons"""
    
    class Meta:
        model = User
    
    email = factory.Sequence(lambda n: f'teacher{n}@example.com')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    user_type = 'teacher'
    is_approved = True
    bio = 'Experienced music instructor'
    instruments = 'Piano, Guitar'
    hourly_rate = Decimal('75.00')
    
    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        if not create:
            return
        password = extracted or 'password123'
        obj.set_password(password)
        obj.save()
    
    @factory.post_generation
    def lessons(obj, create, extracted, **kwargs):
        if not create:
            return
        # Create 3 completed lessons for this teacher
        lessons = CompletedLessonFactory.create_batch(3, teacher=obj)
        return lessons


class FullBillingScenarioFactory:
    """Factory for creating complete billing scenarios"""
    
    @staticmethod
    def create_teacher_with_invoice():
        """Create a teacher with a pending invoice and lessons"""
        teacher = TeacherUserFactory()
        lessons = CompletedLessonFactory.create_batch(3, teacher=teacher)
        invoice = InvoiceFactory(teacher=teacher, lessons=lessons)
        return teacher, invoice, lessons
    
    @staticmethod
    def create_approval_workflow():
        """Create a complete approval workflow scenario"""
        management = ManagementUserFactory()
        teacher = UnapprovedTeacherFactory()
        return management, teacher
    
    @staticmethod
    def create_lesson_request_workflow():
        """Create a lesson request workflow scenario"""
        teacher = TeacherUserFactory()
        student = StudentUserFactory()
        lesson = LessonFactory(teacher=teacher, student=student, status='requested')
        return teacher, student, lesson


# Test data generators for Swagger examples
class SwaggerExampleData:
    """Generate example data that matches Swagger documentation"""
    
    @staticmethod
    def teacher_example():
        """Generate teacher data matching Swagger examples"""
        return {
            "id": 1,
            "email": "john.doe@example.com",
            "first_name": "John",
            "last_name": "Doe",
            "user_type": "teacher",
            "bio": "Classical piano instructor with 10+ years experience",
            "instruments": "Piano, Organ",
            "hourly_rate": "75.00",
            "phone_number": "555-0123",
            "address": "123 Music St, City, State",
            "is_approved": True
        }
    
    @staticmethod
    def lesson_submission_example():
        """Generate lesson submission data matching Swagger examples"""
        return {
            "month": "January 2024",
            "lessons": [
                {
                    "student_name": "John Smith",
                    "student_email": "john@example.com",
                    "scheduled_date": "2024-01-15T14:00:00Z",
                    "duration": 1.0,
                    "rate": 65.00,
                    "teacher_notes": "Worked on scales and arpeggios"
                },
                {
                    "student_name": "Sarah Johnson",
                    "scheduled_date": "2024-01-16T10:00:00Z",
                    "duration": 1.5,
                    "rate": 70.00,
                    "teacher_notes": "Advanced technique work"
                }
            ]
        }
    
    @staticmethod
    def authentication_example():
        """Generate authentication data matching Swagger examples"""
        return {
            "email": "teacher@example.com",
            "password": "securepassword123"
        }
    
    @staticmethod
    def authentication_response_example():
        """Generate authentication response matching Swagger examples"""
        return {
            "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoxLCJlbWFpbCI6InRlYWNoZXJAZXhhbXBsZS5jb20iLCJ1c2VyX3R5cGUiOiJ0ZWFjaGVyIiwiaXNfYXBwcm92ZWQiOnRydWUsImV4cCI6MTcwNTQ3MjgwMH0.signature",
            "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoxLCJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTcwNTU1OTIwMH0.signature",
            "user": {
                "email": "teacher@example.com",
                "name": "John Doe",
                "user_id": 1,
                "user_type": "teacher",
                "is_approved": True
            }
        }
