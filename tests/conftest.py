"""
Shared test fixtures and configuration for pytest.

This file is automatically loaded by pytest and provides fixtures
available to all test files.
"""

import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from billing.models import School, SchoolSettings

User = get_user_model()


@pytest.fixture
def school(db):
    """Create a test school."""
    return School.objects.create(
        name="Test School",
        subdomain="testschool",
        email="test@testschool.com",
        hst_rate=Decimal("13.00"),
        gst_rate=Decimal("5.00"),
        pst_rate=Decimal("0.00"),
        billing_cycle_day=1,
        payment_terms_days=7,
        cancellation_notice_hours=24,
        street_address="123 Test St",
        city="Toronto",
        province="ON",
        postal_code="M5H 2N2",
        is_active=True
    )


@pytest.fixture
def school_settings(school):
    """Create school settings for the test school."""
    return SchoolSettings.objects.create(
        school=school,
        online_teacher_rate=Decimal("45.00"),
        online_student_rate=Decimal("60.00"),
        inperson_student_rate=Decimal("100.00")
    )


@pytest.fixture
def second_school(db):
    """Create a second test school for isolation testing."""
    return School.objects.create(
        name="Second Test School",
        subdomain="secondschool",
        email="test@secondschool.com",
        hst_rate=Decimal("13.00"),
        gst_rate=Decimal("5.00"),
        pst_rate=Decimal("0.00"),
        billing_cycle_day=1,
        payment_terms_days=7,
        cancellation_notice_hours=24,
        street_address="456 Second Ave",
        city="Vancouver",
        province="BC",
        postal_code="V6B 1A1",
        is_active=True
    )


@pytest.fixture
def second_school_settings(second_school):
    """Create school settings for the second test school with different rates."""
    return SchoolSettings.objects.create(
        school=second_school,
        online_teacher_rate=Decimal("40.00"),  # Different rates for isolation testing
        online_student_rate=Decimal("55.00"),
        inperson_student_rate=Decimal("90.00")
    )


@pytest.fixture
def management_user(school, db):
    """Create a management user for testing."""
    return User.objects.create_user(
        email="management@test.com",
        password="testpass123",
        user_type="management",
        first_name="Test",
        last_name="Manager",
        school=school,
        is_approved=True
    )


@pytest.fixture
def teacher_user(school, db):
    """Create a teacher user for testing."""
    return User.objects.create_user(
        email="teacher@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Test",
        last_name="Teacher",
        hourly_rate=Decimal("80.00"),
        school=school,
        is_approved=True
    )


@pytest.fixture
def student_user(school, teacher_user, db):
    """Create a student user for testing with a completed lesson to avoid trial auto-detection."""
    from billing.models import Lesson
    from django.utils import timezone
    from decimal import Decimal

    student = User.objects.create_user(
        email="student@test.com",
        password="testpass123",
        user_type="student",
        first_name="Test",
        last_name="Student",
        school=school,
        is_approved=True
    )

    # Create a completed lesson so student is not detected as first-time (trial)
    Lesson.objects.create(
        teacher=teacher_user,
        student=student,
        school=school,
        lesson_type='online',
        is_trial=True,  # This was their trial lesson
        teacher_rate=Decimal("45.00"),
        student_rate=Decimal("0.00"),
        scheduled_date=timezone.now() - timezone.timedelta(days=30),
        duration=1.0,
        status='completed'
    )

    return student


@pytest.fixture
def unapproved_teacher(school, db):
    """Create an unapproved teacher for testing approval workflows."""
    return User.objects.create_user(
        email="pending@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Pending",
        last_name="Teacher",
        school=school,
        is_approved=False
    )
