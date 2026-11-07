"""
Model-level billing rules (MAP-302).

A teacher batch's expected lessons come from the teacher's active recurring
schedules, and only for students who are billable: not removed (is_active)
and enrolment status 'active'.
"""

from datetime import date, time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from billing.models import MonthlyInvoiceBatch, RecurringLessonsSchedule

User = get_user_model()

YEAR, MONTH = 2026, 6


def _student(school, teacher, value, *, is_active=True):
    student = User.objects.create_user(
        email=f'{value}{"" if is_active else "-removed"}@models.test', password='x',
        user_type='student', first_name='S', last_name=value, school=school,
        is_approved=True,
    )
    student.status = value
    student.is_active = is_active
    student.save(update_fields=['status', 'is_active'])
    RecurringLessonsSchedule.objects.create(
        teacher=teacher, student=student, school=school, day_of_week=0,
        start_time=time(17, 0), duration=Decimal('1.00'), teacher_rate=Decimal('45.00'),
        student_rate=Decimal('60.00'), start_date=date(YEAR, MONTH, 1),
    )
    return student


@pytest.mark.django_db
def test_expected_lessons_exclude_non_active_students(school, teacher_user):
    active = _student(school, teacher_user, 'active')
    for value, _ in User.STUDENT_STATUSES:
        if value != 'active':
            _student(school, teacher_user, value)
    _student(school, teacher_user, 'active', is_active=False)  # removed
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user, school=school, month=MONTH, year=YEAR, status='draft',
    )

    lessons = batch.get_scheduled_lessons_data()

    assert lessons, 'the active student has Monday lessons this month'
    assert {item['student'].id for item in lessons} == {active.id}


@pytest.mark.django_db
def test_billable_students_helper(school, teacher_user, second_school):
    active = _student(school, teacher_user, 'active')
    _student(school, teacher_user, 'waitlist')
    _student(school, teacher_user, 'active', is_active=False)

    assert list(User.objects.billable_students(school)) == [active]
    assert list(teacher_user.assigned_students.billable_students(school)) == []
    active.assigned_teachers.add(teacher_user)
    assert list(teacher_user.assigned_students.billable_students(school)) == [active]
    assert not User.objects.billable_students(second_school).exists()
