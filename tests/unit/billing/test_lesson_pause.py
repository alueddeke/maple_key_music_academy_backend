"""
Unit tests for RecurringLessonsSchedule pause window feature.

Covers five behaviors of generate_lessons_for_month when pause_start/pause_end are set:
  1. Date-range pause: paused months return [] or exclude in-window dates.
  2. Open-ended pause: pause_start only -> July onward excluded, June unaffected.
  3. Auto-resume: pause_end=Aug 31 -> September generates normally (no manual step).
  4. No pause: pause_start=None -> identical to pre-pause behavior (regression guard).
  5. Inclusive boundary: a date equal to pause_start or pause_end is excluded.

These tests are written in RED (failing) state before the model fields are added.
"""

import pytest
from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model

from billing.models import RecurringLessonsSchedule

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def teacher_pause(school, db):
    from billing.models import SchoolSettings
    SchoolSettings.objects.get_or_create(
        school=school,
        defaults={
            'online_teacher_rate': Decimal('45.00'),
            'online_student_rate': Decimal('60.00'),
            'inperson_student_rate': Decimal('100.00'),
        }
    )
    return User.objects.create_user(
        email="teacher_pause@test.com",
        password="testpass123",
        user_type="teacher",
        first_name="Pause",
        last_name="Teacher",
        hourly_rate=Decimal("50.00"),
        school=school,
        is_approved=True,
    )


@pytest.fixture
def student_pause(school, db):
    return User.objects.create_user(
        email="student_pause@test.com",
        password="testpass123",
        user_type="student",
        first_name="Pause",
        last_name="Student",
        school=school,
        is_approved=True,
    )


@pytest.fixture
def schedule_pause(teacher_pause, student_pause, school, db):
    """A Wednesday recurring schedule starting 2026-01-07."""
    return RecurringLessonsSchedule.objects.create(
        teacher=teacher_pause,
        student=student_pause,
        school=school,
        day_of_week=2,  # Wednesday
        start_time="15:00",
        duration=Decimal("1.0"),
        lesson_type="in_person",
        teacher_rate=Decimal("50.00"),
        student_rate=Decimal("100.00"),
        is_active=True,
        start_date=date(2026, 1, 7),
        created_by=teacher_pause,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wednesdays_in(year, month):
    """Return all Wednesday dates in the given month (manual reference)."""
    import calendar
    from datetime import timedelta
    num_days = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, num_days)
    days_until_wed = (2 - month_start.weekday()) % 7
    first_wed = month_start + timedelta(days=days_until_wed)
    result = []
    d = first_wed
    while d <= month_end:
        result.append(d)
        d += timedelta(days=7)
    return result


# ---------------------------------------------------------------------------
# Case 4: No pause -- regression guard (no pause_start)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestNoPauseRegression:
    """pause_start=None -> behavior identical to today."""

    def test_june_returns_all_wednesdays_when_no_pause(self, schedule_pause):
        result = schedule_pause.generate_lessons_for_month(2026, 6)
        expected = _wednesdays_in(2026, 6)
        assert result == expected

    def test_july_returns_all_wednesdays_when_no_pause(self, schedule_pause):
        result = schedule_pause.generate_lessons_for_month(2026, 7)
        expected = _wednesdays_in(2026, 7)
        assert result == expected


# ---------------------------------------------------------------------------
# Case 1: Date-range pause (pause_start + pause_end both set)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDateRangePause:
    """pause_start=Jul 1, pause_end=Aug 31 -- July and August excluded; June and Sep unaffected."""

    def _apply_pause(self, schedule):
        schedule.pause_start = date(2026, 7, 1)
        schedule.pause_end = date(2026, 8, 31)
        schedule.save()

    def test_july_excluded(self, schedule_pause):
        self._apply_pause(schedule_pause)
        result = schedule_pause.generate_lessons_for_month(2026, 7)
        assert result == []

    def test_august_excluded(self, schedule_pause):
        self._apply_pause(schedule_pause)
        result = schedule_pause.generate_lessons_for_month(2026, 8)
        assert result == []

    def test_june_unaffected(self, schedule_pause):
        self._apply_pause(schedule_pause)
        result = schedule_pause.generate_lessons_for_month(2026, 6)
        expected = _wednesdays_in(2026, 6)
        assert result == expected

    def test_september_unaffected(self, schedule_pause):
        """Auto-resume: September should return normal Wednesday dates."""
        self._apply_pause(schedule_pause)
        result = schedule_pause.generate_lessons_for_month(2026, 9)
        expected = _wednesdays_in(2026, 9)
        assert result == expected


# ---------------------------------------------------------------------------
# Case 2: Open-ended pause (pause_start set, pause_end=None)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestOpenEndedPause:
    """pause_start=Jul 1, pause_end=None -> July onward all excluded; June unaffected."""

    def _apply_pause(self, schedule):
        schedule.pause_start = date(2026, 7, 1)
        schedule.pause_end = None
        schedule.save()

    def test_june_unaffected(self, schedule_pause):
        self._apply_pause(schedule_pause)
        result = schedule_pause.generate_lessons_for_month(2026, 6)
        expected = _wednesdays_in(2026, 6)
        assert result == expected

    def test_july_excluded(self, schedule_pause):
        self._apply_pause(schedule_pause)
        result = schedule_pause.generate_lessons_for_month(2026, 7)
        assert result == []

    def test_september_also_excluded(self, schedule_pause):
        """Open-ended: months after pause_start with no end date are also excluded."""
        self._apply_pause(schedule_pause)
        result = schedule_pause.generate_lessons_for_month(2026, 9)
        assert result == []


# ---------------------------------------------------------------------------
# Case 3: Auto-resume (pause_end set, September after pause_end)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAutoResume:
    """pause_end=Aug 31 -> September auto-resumes with normal dates, no manual flip."""

    def test_september_auto_resumes(self, schedule_pause):
        schedule_pause.pause_start = date(2026, 7, 1)
        schedule_pause.pause_end = date(2026, 8, 31)
        schedule_pause.save()
        result = schedule_pause.generate_lessons_for_month(2026, 9)
        expected = _wednesdays_in(2026, 9)
        assert result == expected, (
            f"Expected {expected} but got {result}; "
            "auto-resume should work without manual schedule flip."
        )


# ---------------------------------------------------------------------------
# Case 5: Inclusive boundary edge cases
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestInclusiveBoundary:
    """A date equal to pause_start or pause_end is excluded (inclusive window)."""

    def test_pause_start_date_itself_excluded(self, schedule_pause):
        """Jul 1, 2026 is a Wednesday -- it is exactly pause_start and must be excluded."""
        schedule_pause.pause_start = date(2026, 7, 1)
        schedule_pause.pause_end = date(2026, 7, 31)
        schedule_pause.save()
        result = schedule_pause.generate_lessons_for_month(2026, 7)
        assert date(2026, 7, 1) not in result

    def test_pause_end_date_itself_excluded(self, schedule_pause):
        """Aug 26, 2026 is a Wednesday; when pause_end=Aug 26 it must be excluded."""
        schedule_pause.pause_start = date(2026, 8, 1)
        schedule_pause.pause_end = date(2026, 8, 26)
        schedule_pause.save()
        result = schedule_pause.generate_lessons_for_month(2026, 8)
        assert date(2026, 8, 26) not in result

    def test_date_after_pause_end_included(self, schedule_pause):
        """Sep 2, 2026 (first Wednesday in Sep) should be included when pause_end=Aug 31."""
        schedule_pause.pause_start = date(2026, 7, 1)
        schedule_pause.pause_end = date(2026, 8, 31)
        schedule_pause.save()
        result = schedule_pause.generate_lessons_for_month(2026, 9)
        assert date(2026, 9, 2) in result

    def test_date_before_pause_start_included(self, schedule_pause):
        """Jun 24, 2026 (last Wednesday in June) should be included when pause_start=Jul 1."""
        schedule_pause.pause_start = date(2026, 7, 1)
        schedule_pause.pause_end = date(2026, 8, 31)
        schedule_pause.save()
        result = schedule_pause.generate_lessons_for_month(2026, 6)
        assert date(2026, 6, 24) in result
