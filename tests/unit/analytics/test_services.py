"""Metric formula tests (deterministic via injected `today`)."""

from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from analytics.models import MetricGoal, ScheduleInstrument, StudentExitRecord
from analytics.services import (
    compute_current_metrics,
    compute_goals,
    compute_month_rows,
    compute_overview,
)
from billing.models import Lesson, SchoolExpenseItem

# June 2026 has 5 Mondays (1, 8, 15, 22, 29)
JUNE = date(2026, 6, 15)


@pytest.mark.django_db
class TestMonthRows:
    def test_mrr_formula_scheduled_revenue(self, school, active_schedule):
        rows = compute_month_rows(school, months=1, today=JUNE)
        assert len(rows) == 1
        row = rows[0]
        assert row['period'] == '2026-06'
        # 5 Mondays × 1.0h × $60 = $300
        assert row['mrr'] == '300.00'

    def test_inactive_schedule_excluded_from_mrr(self, school, active_schedule):
        active_schedule.is_active = False
        active_schedule.save()
        rows = compute_month_rows(school, months=1, today=JUNE)
        assert rows[0]['mrr'] == '0.00'

    def test_expenses_summed_by_period(self, school, active_schedule):
        SchoolExpenseItem.objects.create(
            school=school,
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            title='Rent',
            amount=Decimal('500.00'),
        )
        rows = compute_month_rows(school, months=1, today=JUNE)
        assert rows[0]['expenses'] == '500.00'

    def test_returns_requested_month_count(self, school):
        rows = compute_month_rows(school, months=6, today=JUNE)
        assert len(rows) == 6
        assert rows[0]['period'] == '2026-01'
        assert rows[-1]['period'] == '2026-06'

    def test_new_enrollment_counted_in_first_lesson_month(
        self, school, teacher_user, student_user
    ):
        # student_user fixture already has a trial lesson ~30 days ago;
        # its month is that student's first-lesson month.
        first = Lesson.objects.filter(student=student_user).earliest('scheduled_date')
        first_month = first.scheduled_date
        rows = compute_month_rows(
            school, months=1,
            today=date(first_month.year, first_month.month, 15),
        )
        assert rows[0]['new_enrollments'] == 1


@pytest.mark.django_db
class TestCurrentMetrics:
    def test_active_students_and_ratio(self, school, active_schedule):
        current = compute_current_metrics(school, today=JUNE)
        assert current['active_students'] == 1
        assert current['active_teachers'] == 1
        assert current['student_teacher_ratio'] == 1.0

    def test_utilization_null_without_teacher_profiles_app(
        self, school, active_schedule
    ):
        # teacher_profiles (MAP-30) is not installed on this branch —
        # utilization must degrade to None, not crash.
        current = compute_current_metrics(school, today=JUNE)
        assert current['utilization_rate'] is None

    def test_duration_mix(self, school, active_schedule):
        current = compute_current_metrics(school, today=JUNE)
        assert current['duration_mix'] == {'60 min': 1}

    def test_revenue_by_instrument_uses_tag_and_uncategorized(
        self, school, active_schedule
    ):
        current = compute_current_metrics(school, today=JUNE)
        assert current['revenue_by_instrument'] == [
            {'instrument': 'Uncategorized', 'amount': '300.00'}
        ]
        ScheduleInstrument.objects.create(
            schedule=active_schedule, instrument='Piano'
        )
        current = compute_current_metrics(school, today=JUNE)
        assert current['revenue_by_instrument'] == [
            {'instrument': 'Piano', 'amount': '300.00'}
        ]

    def test_trial_conversion(self, school, teacher_user, student_user):
        # student_user has a trial lesson only → 0% conversion
        current = compute_current_metrics(school, today=JUNE)
        assert current['trial_conversion_rate'] == 0.0
        # add a later real lesson → 100%
        Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=school,
            lesson_type='online',
            is_trial=False,
            teacher_rate=Decimal('45.00'),
            student_rate=Decimal('60.00'),
            scheduled_date=timezone.now(),
            duration=1.0,
            status='completed',
        )
        current = compute_current_metrics(school, today=JUNE)
        assert current['trial_conversion_rate'] == 100.0

    def test_cpa_null_without_categorized_ad_spend(self, school, active_schedule):
        current = compute_current_metrics(school, today=JUNE)
        assert current['cpa'] is None

    def test_exit_reasons_grouped(self, school, student_user, management_user):
        StudentExitRecord.objects.create(
            student=student_user, school=school,
            reason='price', recorded_by=management_user,
        )
        current = compute_current_metrics(school, today=JUNE)
        assert current['exit_reasons'] == [{'reason': 'price', 'count': 1}]


@pytest.mark.django_db
class TestGoals:
    def test_goal_resolves_current_value(self, school, active_schedule):
        MetricGoal.objects.create(
            school=school, metric='mrr', target=Decimal('1000.00')
        )
        overview = compute_overview(school, months=1, today=JUNE)
        goal = overview['goals'][0]
        assert goal['metric'] == 'mrr'
        assert goal['target'] == '1000.00'
        assert goal['current_value'] == '300.00'

    def test_goals_empty_by_default(self, school):
        rows = compute_month_rows(school, months=1, today=JUNE)
        current = compute_current_metrics(school, today=JUNE)
        assert compute_goals(school, rows, current) == []


@pytest.mark.django_db
class TestTestDataFilter:
    """MAP-113: analytics exclude test-domain accounts when the prod flag is on."""

    def test_filter_off_by_default_test_data_counted(self, school, active_schedule):
        active_schedule.student.email = 'kid@maplekeytest.com'
        active_schedule.student.save(update_fields=['email'])
        rows = compute_month_rows(school, months=1, today=JUNE)
        assert rows[0]['mrr'] == '300.00'

    def test_filter_on_excludes_test_domain_schedules(
        self, school, active_schedule, settings
    ):
        settings.ANALYTICS_EXCLUDE_TEST_DATA = True
        settings.TEST_ACCOUNT_EMAIL_DOMAINS = ['maplekeytest.com']
        active_schedule.student.email = 'kid@maplekeytest.com'
        active_schedule.student.save(update_fields=['email'])
        rows = compute_month_rows(school, months=1, today=JUNE)
        assert rows[0]['mrr'] == '0.00'

    def test_filter_on_keeps_real_accounts(self, school, active_schedule, settings):
        settings.ANALYTICS_EXCLUDE_TEST_DATA = True
        settings.TEST_ACCOUNT_EMAIL_DOMAINS = ['maplekeytest.com']
        # student@test.com is NOT a test domain in this config
        rows = compute_month_rows(school, months=1, today=JUNE)
        assert rows[0]['mrr'] == '300.00'

    def test_filter_on_excludes_test_teachers_from_current(
        self, school, teacher_user, settings
    ):
        settings.ANALYTICS_EXCLUDE_TEST_DATA = True
        settings.TEST_ACCOUNT_EMAIL_DOMAINS = ['maplekeytest.com']
        teacher_user.email = 'teach@maplekeytest.com'
        teacher_user.save(update_fields=['email'])
        current = compute_current_metrics(school, today=JUNE)
        assert current['active_teachers'] == 0
