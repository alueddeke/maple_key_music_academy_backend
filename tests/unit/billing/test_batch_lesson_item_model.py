"""
BatchLessonItem money helpers on an unsaved instance.

P0 audit 2026-09-09: the float default on duration made
calculate_teacher_payment() raise TypeError (Decimal * float) before the row
was ever refetched — the 201 body of batch_add_lesson hit exactly that.
"""
from decimal import Decimal

import pytest

from billing.models import BatchLessonItem, MonthlyInvoiceBatch


@pytest.mark.django_db
def test_default_duration_computes_money_on_unsaved_instance(school, teacher_user, student_user, school_settings):
    batch = MonthlyInvoiceBatch.objects.create(teacher=teacher_user, school=school, month=9, year=2026, status='draft')
    item = BatchLessonItem(
        batch=batch, student=student_user, scheduled_date='2026-09-03', start_time='14:00:00',
        lesson_type='in_person', status='completed',
        teacher_rate=teacher_user.hourly_rate, student_rate=school_settings.inperson_student_rate,
    )

    assert item.calculate_teacher_payment() == teacher_user.hourly_rate * item.duration
    assert item.calculate_student_charge() == school_settings.inperson_student_rate * item.duration
    assert isinstance(item.duration, Decimal)
