"""
Unit tests for RecurringLessonsSchedule.interval_weeks (MAP-208).

generate_lessons_for_month with interval_weeks=2 keeps only the day_of_week
dates a whole multiple of 2 weeks after start_date — the cadence anchor. The
cadence does not reset at a month boundary, a pause window skips dates without
shifting it, end_date still applies, and interval_weeks=1 (the default) is the
pre-MAP-208 behaviour unchanged.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

import pytest

from billing.models import RecurringLessonsSchedule

MONDAY = 0
# 1 June 2026 is a Monday; June 2026 has five Mondays (1, 8, 15, 22, 29).
JUNE = (2026, 6)
JULY = (2026, 7)


# ---------------------------------------------------------------------------
# Reference helpers — independent of the model's implementation
# ---------------------------------------------------------------------------

def _weekday_dates_in(year, month, weekday):
    """Every date of ``weekday`` in the month."""
    last = calendar.monthrange(year, month)[1]
    return [
        d for d in (date(year, month, n) for n in range(1, last + 1))
        if d.weekday() == weekday
    ]


def _on_cadence(dates, anchor, interval_weeks):
    """The ticket's rule: dates a whole multiple of ``interval_weeks`` weeks after ``anchor``."""
    return [
        d for d in dates
        if d >= anchor and ((d - anchor).days // 7) % interval_weeks == 0
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_schedule(school, teacher_user, student_user):
    """Monday 15:00 schedule starting 1 June 2026; overrides per test."""
    def _make(**overrides):
        fields = dict(
            teacher=teacher_user,
            student=student_user,
            school=school,
            day_of_week=MONDAY,
            start_time="15:00",
            duration=Decimal("1.0"),
            lesson_type="in_person",
            teacher_rate=Decimal("50.00"),
            student_rate=Decimal("100.00"),
            is_active=True,
            start_date=date(2026, 6, 1),
        )
        fields.update(overrides)
        return RecurringLessonsSchedule.objects.create(**fields)
    return _make


# ---------------------------------------------------------------------------
# Every 2 weeks — anchored to start_date
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBiweeklyAnchoredToStartDate:

    def test_five_monday_month_from_first_monday_anchor(self, make_schedule):
        sched = make_schedule(interval_weeks=2, start_date=date(2026, 6, 1))
        mondays = _weekday_dates_in(*JUNE, MONDAY)
        assert len(mondays) == 5

        result = sched.generate_lessons_for_month(*JUNE)

        assert result == _on_cadence(mondays, sched.start_date, 2)
        assert [(d - sched.start_date).days for d in result] == [0, 14, 28]

    def test_five_monday_month_from_second_monday_anchor(self, make_schedule):
        sched = make_schedule(interval_weeks=2, start_date=date(2026, 6, 8))
        mondays = _weekday_dates_in(*JUNE, MONDAY)

        result = sched.generate_lessons_for_month(*JUNE)

        assert result == _on_cadence(mondays, sched.start_date, 2)
        assert [(d - sched.start_date).days for d in result] == [0, 14]

    def test_cadence_holds_across_month_boundary(self, make_schedule):
        sched = make_schedule(interval_weeks=2, start_date=date(2026, 6, 1))

        june = sched.generate_lessons_for_month(*JUNE)
        july = sched.generate_lessons_for_month(*JULY)

        assert july[0] - june[-1] == timedelta(days=14)
        assert july == _on_cadence(_weekday_dates_in(*JULY, MONDAY), sched.start_date, 2)

    def test_mid_month_start_date_is_the_first_occurrence(self, make_schedule):
        sched = make_schedule(interval_weeks=2, start_date=date(2026, 6, 15))

        result = sched.generate_lessons_for_month(*JUNE)

        assert result[0] == sched.start_date
        assert result == _on_cadence(_weekday_dates_in(*JUNE, MONDAY), sched.start_date, 2)
        assert [(d - sched.start_date).days for d in result] == [0, 14]

    def test_pause_skips_dates_without_shifting_cadence(self, make_schedule):
        sched = make_schedule(
            interval_weeks=2, start_date=date(2026, 6, 1),
            pause_start=date(2026, 6, 15), pause_end=date(2026, 6, 15),
        )
        unpaused = _on_cadence(_weekday_dates_in(*JUNE, MONDAY), sched.start_date, 2)
        assert date(2026, 6, 15) in unpaused  # the pause covers an on-cadence date

        result = sched.generate_lessons_for_month(*JUNE)

        assert result == [d for d in unpaused if d != date(2026, 6, 15)]
        # The dates either side of the pause are still 4 weeks apart — no shift.
        assert result[-1] - result[0] == timedelta(days=28)

    def test_end_date_still_excludes_later_dates(self, make_schedule):
        sched = make_schedule(
            interval_weeks=2, start_date=date(2026, 6, 1), end_date=date(2026, 6, 20),
        )
        on_cadence = _on_cadence(_weekday_dates_in(*JUNE, MONDAY), sched.start_date, 2)

        result = sched.generate_lessons_for_month(*JUNE)

        assert result == [d for d in on_cadence if d <= sched.end_date]
        assert len(result) < len(on_cadence)


# ---------------------------------------------------------------------------
# Weekly (interval_weeks=1) — unchanged behaviour
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestWeeklyUnchanged:

    def test_default_interval_returns_every_weekday_date(self, make_schedule):
        sched = make_schedule()  # interval_weeks not supplied

        assert sched.generate_lessons_for_month(*JUNE) == _weekday_dates_in(*JUNE, MONDAY)
        assert sched.generate_lessons_for_month(*JULY) == _weekday_dates_in(*JULY, MONDAY)

    def test_explicit_weekly_matches_default(self, make_schedule):
        # Different start_time keeps the (teacher, student, day, time) uniqueness.
        default = make_schedule(start_time="15:00")
        explicit = make_schedule(start_time="16:00", interval_weeks=1)

        for year, month in (JUNE, JULY):
            assert (
                explicit.generate_lessons_for_month(year, month)
                == default.generate_lessons_for_month(year, month)
            )
