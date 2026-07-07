"""Fixtures for analytics tests."""

from datetime import time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from billing.models import RecurringLessonsSchedule

User = get_user_model()


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


@pytest.fixture
def active_schedule(school, teacher_user, student_user, db):
    """Weekly Monday 1h lesson at $60 student / $45 teacher, active, no end."""
    return RecurringLessonsSchedule.objects.create(
        school=school,
        teacher=teacher_user,
        student=student_user,
        day_of_week=0,  # Monday
        start_time=time(15, 0),
        duration=Decimal('1.0'),
        lesson_type='online',
        teacher_rate=Decimal('45.00'),
        student_rate=Decimal('60.00'),
        is_active=True,
        start_date='2025-01-06',
    )
