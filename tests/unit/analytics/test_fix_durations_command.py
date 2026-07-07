"""Tests for the legacy duration repair command."""

from datetime import time
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from billing.models import RecurringLessonsSchedule


@pytest.fixture
def legacy_schedule(school, teacher_user, student_user, db):
    """A legacy row that stored 60 MINUTES as 60.00 hours."""
    return RecurringLessonsSchedule.objects.create(
        school=school,
        teacher=teacher_user,
        student=student_user,
        day_of_week=2,
        start_time=time(10, 0),
        duration=Decimal('60.00'),
        lesson_type='in_person',
        teacher_rate=Decimal('45.00'),
        student_rate=Decimal('60.00'),
        is_active=True,
        start_date='2025-01-08',
    )


@pytest.fixture
def healthy_schedule(school, teacher_user, student_user, db):
    return RecurringLessonsSchedule.objects.create(
        school=school,
        teacher=teacher_user,
        student=student_user,
        day_of_week=0,
        start_time=time(15, 0),
        duration=Decimal('1.50'),
        lesson_type='online',
        teacher_rate=Decimal('45.00'),
        student_rate=Decimal('60.00'),
        is_active=True,
        start_date='2025-01-06',
    )


@pytest.mark.django_db
class TestFixLegacyScheduleDurations:
    def test_dry_run_reports_but_does_not_change(self, legacy_schedule):
        out = StringIO()
        call_command('fix_legacy_schedule_durations', stdout=out)
        legacy_schedule.refresh_from_db()
        assert legacy_schedule.duration == Decimal('60.00')
        assert 'DRY RUN' in out.getvalue()
        assert '60.00h → 1.00h' in out.getvalue()

    def test_apply_converts_minutes_to_hours(self, legacy_schedule):
        call_command('fix_legacy_schedule_durations', '--apply', stdout=StringIO())
        legacy_schedule.refresh_from_db()
        assert legacy_schedule.duration == Decimal('1.00')

    def test_healthy_rows_untouched(self, legacy_schedule, healthy_schedule):
        call_command('fix_legacy_schedule_durations', '--apply', stdout=StringIO())
        healthy_schedule.refresh_from_db()
        assert healthy_schedule.duration == Decimal('1.50')

    def test_rates_not_modified(self, legacy_schedule):
        call_command('fix_legacy_schedule_durations', '--apply', stdout=StringIO())
        legacy_schedule.refresh_from_db()
        assert legacy_schedule.teacher_rate == Decimal('45.00')
        assert legacy_schedule.student_rate == Decimal('60.00')

    def test_noop_when_clean(self, healthy_schedule):
        out = StringIO()
        call_command('fix_legacy_schedule_durations', '--apply', stdout=out)
        assert 'nothing to do' in out.getvalue()

    def test_ninety_minute_row_converts(self, school, teacher_user, student_user):
        row = RecurringLessonsSchedule.objects.create(
            school=school,
            teacher=teacher_user,
            student=student_user,
            day_of_week=4,
            start_time=time(9, 0),
            duration=Decimal('90.00'),
            lesson_type='online',
            teacher_rate=Decimal('45.00'),
            student_rate=Decimal('60.00'),
            is_active=True,
            start_date='2025-01-10',
        )
        call_command('fix_legacy_schedule_durations', '--apply', stdout=StringIO())
        row.refresh_from_db()
        assert row.duration == Decimal('1.50')
