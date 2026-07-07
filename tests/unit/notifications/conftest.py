"""Fixtures for notifications tests."""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def second_teacher(school, db):
    return User.objects.create_user(
        email="teacher2@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Second",
        last_name="Teacher",
        school=school,
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
