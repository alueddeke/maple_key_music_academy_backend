"""Fixtures for teacher_profiles endpoint tests."""

import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def second_teacher(school, db):
    """A second teacher in the same school (for cross-teacher access tests)."""
    return User.objects.create_user(
        email="teacher2@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Second",
        last_name="Teacher",
        hourly_rate=Decimal("70.00"),
        school=school,
        is_approved=True,
    )


@pytest.fixture
def other_school_teacher(second_school, db):
    """A teacher in a different school (for school-isolation tests)."""
    return User.objects.create_user(
        email="teacher-other@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Other",
        last_name="School",
        school=second_school,
        is_approved=True,
    )


@pytest.fixture
def teacher_client(api_client, teacher_user):
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def management_client(api_client, management_user):
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.fixture
def student_client(api_client, student_user):
    api_client.force_authenticate(user=student_user)
    return api_client
