"""
Shared test fixtures and configuration for pytest.

This file is automatically loaded by pytest and provides fixtures
available to all test files.
"""

import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def management_user(db):
    """Create a management user for testing."""
    return User.objects.create_user(
        email="management@test.com",
        password="testpass123",
        user_type="management",
        first_name="Test",
        last_name="Manager",
        is_approved=True
    )


@pytest.fixture
def teacher_user(db):
    """Create a teacher user for testing."""
    return User.objects.create_user(
        email="teacher@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Test",
        last_name="Teacher",
        hourly_rate=Decimal("80.00"),
        is_approved=True
    )


@pytest.fixture
def student_user(db):
    """Create a student user for testing."""
    return User.objects.create_user(
        email="student@test.com",
        password="testpass123",
        user_type="student",
        first_name="Test",
        last_name="Student",
        is_approved=True
    )


@pytest.fixture
def unapproved_teacher(db):
    """Create an unapproved teacher for testing approval workflows."""
    return User.objects.create_user(
        email="pending@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Pending",
        last_name="Teacher",
        is_approved=False
    )
