"""
Integration tests for cross-school data isolation.

These tests verify that:
- Users in school A cannot access data from school B
- Queries properly filter by school
- No data leakage between schools
"""

import pytest
from decimal import Decimal
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth import get_user_model
from billing.models import School, Lesson, Invoice, BillableContact
from rest_framework.test import APIClient
from rest_framework import status

User = get_user_model()


@pytest.mark.django_db
class TestSchoolIsolation:
    """Test that schools are properly isolated from each other."""

    @pytest.fixture
    def school1_teacher(self, school, db):
        """Teacher from school 1."""
        return User.objects.create_user(
            email="teacher1@school1.com",
            password="test123",
            user_type="teacher",
            school=school,
            hourly_rate=Decimal("80.00"),
            is_approved=True
        )

    @pytest.fixture
    def school1_student(self, school, db):
        """Student from school 1."""
        return User.objects.create_user(
            email="student1@school1.com",
            password="test123",
            user_type="student",
            school=school,
            is_approved=True
        )

    @pytest.fixture
    def school2_teacher(self, second_school, db):
        """Teacher from school 2."""
        return User.objects.create_user(
            email="teacher2@school2.com",
            password="test123",
            user_type="teacher",
            school=second_school,
            hourly_rate=Decimal("75.00"),
            is_approved=True
        )

    @pytest.fixture
    def school2_student(self, second_school, db):
        """Student from school 2."""
        return User.objects.create_user(
            email="student2@school2.com",
            password="test123",
            user_type="student",
            school=second_school,
            is_approved=True
        )

    @pytest.fixture
    def school1_lesson(self, school, school1_teacher, school1_student):
        """Lesson in school 1."""
        return Lesson.objects.create(
            teacher=school1_teacher,
            student=school1_student,
            school=school,
            lesson_type='online',
            scheduled_date=timezone.now(),
            duration=1.0,
            teacher_rate=Decimal("45.00"),
            student_rate=Decimal("60.00"),
            status='confirmed'
        )

    @pytest.fixture
    def school2_lesson(self, second_school, school2_teacher, school2_student):
        """Lesson in school 2."""
        return Lesson.objects.create(
            teacher=school2_teacher,
            student=school2_student,
            school=second_school,
            lesson_type='online',
            scheduled_date=timezone.now(),
            duration=1.0,
            teacher_rate=Decimal("40.00"),
            student_rate=Decimal("55.00"),
            status='confirmed'
        )

    def test_users_assigned_to_correct_school(
        self, school1_teacher, school1_student, school2_teacher, school2_student
    ):
        """Test that users are assigned to their respective schools."""
        assert school1_teacher.school.name == "Test School"
        assert school1_student.school.name == "Test School"
        assert school2_teacher.school.name == "Second Test School"
        assert school2_student.school.name == "Second Test School"

    def test_lessons_assigned_to_correct_school(self, school1_lesson, school2_lesson):
        """Test that lessons are assigned to their respective schools."""
        assert school1_lesson.school.name == "Test School"
        assert school2_lesson.school.name == "Second Test School"

    def test_lesson_query_isolation(
        self, school, second_school, school1_lesson, school2_lesson
    ):
        """Test that querying lessons by school returns only that school's lessons."""
        school1_lessons = Lesson.objects.filter(school=school)
        assert school1_lessons.count() == 1
        assert school1_lessons.first().id == school1_lesson.id

        school2_lessons = Lesson.objects.filter(school=second_school)
        assert school2_lessons.count() == 1
        assert school2_lessons.first().id == school2_lesson.id

    def test_user_query_isolation(
        self, school, second_school, school1_teacher, school2_teacher
    ):
        """Test that querying users by school returns only that school's users."""
        school1_teachers = User.objects.filter(school=school, user_type='teacher')
        assert school1_teachers.count() == 1
        assert school1_teachers.first().id == school1_teacher.id

        school2_teachers = User.objects.filter(school=second_school, user_type='teacher')
        assert school2_teachers.count() == 1
        assert school2_teachers.first().id == school2_teacher.id

    def test_lesson_school_fk_set_from_explicit_school_arg(
        self, school, second_school, school1_teacher, school2_student
    ):
        """
        Lesson.school FK is set to the value passed explicitly at creation.

        This test verifies that the school FK is persisted correctly when a lesson
        is created with teacher and student from different schools. It does NOT assert
        that cross-school lesson creation is rejected — the model permits it; enforcement
        is the responsibility of the view layer (school isolation via request.user.school).
        """
        lesson = Lesson.objects.create(
            teacher=school1_teacher,
            student=school2_student,
            school=school,  # Explicitly set to school1
            lesson_type='online',
            scheduled_date=timezone.now(),
            duration=1.0,
            teacher_rate=Decimal("45.00"),
            student_rate=Decimal("60.00"),
            status='confirmed'
        )

        # Verify lesson is assigned to the school that was passed in explicitly.
        assert lesson.school.id == school.id

    def test_teacher_can_only_see_own_school_lessons(
        self, school1_teacher, school2_teacher, school1_lesson, school2_lesson
    ):
        """Test that a teacher can only query lessons from their own school."""
        # School 1 teacher's lessons
        school1_teacher_lessons = Lesson.objects.filter(
            teacher=school1_teacher,
            school=school1_teacher.school
        )
        assert school1_teacher_lessons.count() == 1
        assert school1_teacher_lessons.first().id == school1_lesson.id

        # School 2 teacher's lessons
        school2_teacher_lessons = Lesson.objects.filter(
            teacher=school2_teacher,
            school=school2_teacher.school
        )
        assert school2_teacher_lessons.count() == 1
        assert school2_teacher_lessons.first().id == school2_lesson.id

        # Cross-school query should return nothing
        cross_school = Lesson.objects.filter(
            teacher=school1_teacher,
            school=school2_teacher.school
        )
        assert cross_school.count() == 0

    def test_invoice_isolation(
        self, school, second_school, school1_teacher, school2_teacher
    ):
        """Test that invoices are isolated by school."""
        # Create invoices for each school
        invoice1 = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=school1_teacher,
            school=school,
            status='pending',
            payment_balance=Decimal("100.00"),
            total_amount=Decimal("100.00")
        )

        invoice2 = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=school2_teacher,
            school=second_school,
            status='pending',
            payment_balance=Decimal("80.00"),
            total_amount=Decimal("80.00")
        )

        # Verify isolation
        school1_invoices = Invoice.objects.filter(school=school)
        assert school1_invoices.count() == 1
        assert school1_invoices.first().id == invoice1.id

        school2_invoices = Invoice.objects.filter(school=second_school)
        assert school2_invoices.count() == 1
        assert school2_invoices.first().id == invoice2.id

    def test_billable_contact_isolation(
        self, school, second_school, school1_student, school2_student
    ):
        """Test that billable contacts are isolated by school."""
        # Create contacts for each school
        contact1 = BillableContact.objects.create(
            student=school1_student,
            school=school,
            contact_type='parent',
            first_name="Parent",
            last_name="One",
            email="parent1@test.com",
            phone="4165551111",
            street_address="123 School1 St",
            city="Toronto",
            province="ON",
            postal_code="M5H 2N2",
            is_primary=True
        )

        contact2 = BillableContact.objects.create(
            student=school2_student,
            school=second_school,
            contact_type='parent',
            first_name="Parent",
            last_name="Two",
            email="parent2@test.com",
            phone="6045552222",
            street_address="456 School2 Ave",
            city="Vancouver",
            province="BC",
            postal_code="V6B 1A1",
            is_primary=True
        )

        # Verify isolation
        school1_contacts = BillableContact.objects.filter(school=school)
        assert school1_contacts.count() == 1
        assert school1_contacts.first().id == contact1.id

        school2_contacts = BillableContact.objects.filter(school=second_school)
        assert school2_contacts.count() == 1
        assert school2_contacts.first().id == contact2.id

    def test_aggregate_queries_respect_school_boundary(
        self, school, second_school, school1_lesson, school2_lesson
    ):
        """Test that aggregate queries respect school boundaries."""
        from django.db.models import Count, Sum

        # Count lessons per school
        school1_count = Lesson.objects.filter(school=school).count()
        school2_count = Lesson.objects.filter(school=second_school).count()

        assert school1_count == 1
        assert school2_count == 1

        # Sum of teacher rates per school
        school1_total = Lesson.objects.filter(school=school).aggregate(
            total=Sum('teacher_rate')
        )['total']
        school2_total = Lesson.objects.filter(school=second_school).aggregate(
            total=Sum('teacher_rate')
        )['total']

        assert school1_total == Decimal("45.00")
        assert school2_total == Decimal("40.00")

    def test_management_user_sees_only_own_school(
        self, school, second_school, school1_teacher, school2_teacher
    ):
        """Test that management users only see data from their own school."""
        management1 = User.objects.create_user(
            email="mgmt1@school1.com",
            password="test123",
            user_type="management",
            school=school,
            is_approved=True
        )

        management2 = User.objects.create_user(
            email="mgmt2@school2.com",
            password="test123",
            user_type="management",
            school=second_school,
            is_approved=True
        )

        # Management 1 should only see school 1 users
        mgmt1_teachers = User.objects.filter(
            school=management1.school,
            user_type='teacher'
        )
        assert mgmt1_teachers.count() == 1
        assert mgmt1_teachers.first().id == school1_teacher.id

        # Management 2 should only see school 2 users
        mgmt2_teachers = User.objects.filter(
            school=management2.school,
            user_type='teacher'
        )
        assert mgmt2_teachers.count() == 1
        assert mgmt2_teachers.first().id == school2_teacher.id


@pytest.mark.django_db
class TestPhase2ManagementSchoolScoping:
    """SEC-04: Management endpoints must filter by school=request.user.school."""

    def test_management_cannot_approve_cross_school_invoice(
        self, api_client, management_user, school, second_school
    ):
        """
        SEC-04: Management from school A cannot approve invoice belonging to school B.
        """
        from billing.models import Invoice
        from decimal import Decimal

        school2_teacher = User.objects.create_user(
            email="teacher_s2@test.com", password="test123",
            user_type="teacher", school=second_school, is_approved=True
        )
        invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=school2_teacher,
            school=second_school,
            status='pending',
            payment_balance=Decimal("100.00"),
            total_amount=Decimal("100.00")
        )

        api_client.force_authenticate(user=management_user)
        url = reverse('approve_teacher_invoice', kwargs={'invoice_id': invoice.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        invoice.refresh_from_db()
        assert invoice.status == 'pending'

    def test_management_cannot_delete_cross_school_user(
        self, api_client, management_user, second_school
    ):
        """
        SEC-04: Management from school A cannot delete user belonging to school B.
        """
        school2_user = User.objects.create_user(
            email="victim@school2.com", password="test123",
            user_type="teacher", school=second_school, is_approved=True
        )

        api_client.force_authenticate(user=management_user)
        url = reverse('management_delete_user', kwargs={'pk': school2_user.id})
        response = api_client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert User.objects.filter(id=school2_user.id).exists()
