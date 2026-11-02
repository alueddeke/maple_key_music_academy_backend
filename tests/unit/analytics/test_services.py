"""Metric formula tests (deterministic via injected `today`)."""

from datetime import date, time
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
from billing.models import (
    BatchLessonItem,
    Invoice,
    Lesson,
    MonthlyInvoiceBatch,
    SchoolExpenseItem,
    StudentInvoice,
)

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

    def test_mrr_biweekly_schedule_counts_anchored_mondays_only(self, school, active_schedule):
        """MAP-208: interval_weeks=2 projects the Mondays on the start_date cadence, not all five."""
        active_schedule.interval_weeks = 2
        active_schedule.save(update_fields=['interval_weeks'])
        active_schedule.refresh_from_db()
        count = len(active_schedule.generate_lessons_for_month(JUNE.year, JUNE.month))
        assert 0 < count < 5
        expected = (
            count
            * Decimal(str(active_schedule.duration))
            * Decimal(str(active_schedule.student_rate))
        )
        rows = compute_month_rows(school, months=1, today=JUNE)
        assert rows[0]['mrr'] == f"{expected:.2f}"

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

    def test_cancellations_teacher_counts_approved_batch_items(
        self, school, teacher_user, student_user
    ):
        """MAP-271: teacher cancels in approved batches, scheduled in the month.
        Draft batches, promo and bare cancelled are not counted."""
        approved = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=6, year=2026, status='approved',
        )
        draft = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=7, year=2026, status='draft',
        )

        def item(batch, day, item_status, month=6):
            return BatchLessonItem.objects.create(
                batch=batch, student=student_user,
                scheduled_date=date(2026, month, day), start_time=time(15, 0),
                duration=Decimal('1.0'), lesson_type='online',
                teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'),
                status=item_status,
            )

        item(approved, 1, 'teacher_cancelled')
        item(approved, 8, 'teacher_cancelled')
        item(approved, 15, 'promo')
        item(approved, 22, 'cancelled')
        item(draft, 29, 'teacher_cancelled')
        item(approved, 2, 'teacher_cancelled', month=5)

        rows = compute_month_rows(school, months=1, today=JUNE)
        assert rows[0]['cancellations_teacher'] == 2
        assert rows[0]['cancelled_lessons'] == 0



def _batch(school, teacher, status='approved', month=6):
    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher, school=school, month=month, year=2026, status=status,
    )


def _item(batch, student, day, item_status='confirmed', *, teacher_rate, student_rate):
    return BatchLessonItem.objects.create(
        batch=batch, student=student,
        scheduled_date=date(2026, batch.month, day), start_time=time(15, 0),
        duration=Decimal('1.0'), lesson_type='online',
        teacher_rate=teacher_rate, student_rate=student_rate,
        status=item_status,
    )


def _payroll_invoice(school, teacher, batch, total):
    invoice = Invoice.objects.create(
        invoice_type='teacher_payment', teacher=teacher, school=school,
        status='pending', created_by=teacher,
        total_amount=total, payment_balance=total,
    )
    batch.invoice = invoice
    batch.save(update_fields=['invoice'])
    return invoice


def _student_invoice(batch, student, amount):
    return StudentInvoice.objects.create(
        batch=batch, student=student, school=batch.school,
        invoice_number=f'INV-T-{batch.pk}-{student.pk}', amount=amount,
        credit_applied=Decimal('0.00'), amount_after_credit=amount,
        billing_contact_name='x', billing_email=student.email, billing_phone='1',
        billing_street_address='1', billing_city='T', billing_province='ON',
        billing_postal_code='M5H 2N2',
    )


@pytest.mark.django_db
class TestTeacherPay:
    """MAP-314: Teacher pay counts every approved batch, not only generated
    payroll invoices; gross margin = billed − teacher pay − expenses."""

    RATES = dict(teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'))

    def test_teacher_pay_counts_approved_batches_without_invoice(
        self, school, teacher_user, student_user
    ):
        batch = _batch(school, teacher_user)
        items = [_item(batch, student_user, d, **self.RATES) for d in (1, 8)]
        expected_pay = sum((i.calculate_teacher_payment() for i in items), Decimal(0))
        billed = Decimal('120.00')
        _student_invoice(batch, student_user, billed)
        SchoolExpenseItem.objects.create(
            school=school, period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
            amount=Decimal('10.00'), title='rent',
        )

        row = compute_month_rows(school, months=1, today=JUNE)[0]
        assert Decimal(row['teacher_pay']) == expected_pay
        assert Decimal(row['teacher_pay_pending']) == expected_pay
        assert Decimal(row['teacher_pay_generated']) == 0
        assert Decimal(row['gross_margin']) == billed - expected_pay - Decimal('10.00')

    def test_teacher_pay_prefers_invoice_total_when_generated(
        self, school, teacher_user, student_user
    ):
        batch = _batch(school, teacher_user)
        item = _item(batch, student_user, 1, **self.RATES)
        adjusted = item.calculate_teacher_payment() + Decimal('7.00')
        _payroll_invoice(school, teacher_user, batch, adjusted)

        row = compute_month_rows(school, months=1, today=JUNE)[0]
        assert Decimal(row['teacher_pay']) == adjusted
        assert Decimal(row['teacher_pay_generated']) == adjusted
        assert Decimal(row['teacher_pay_pending']) == 0

    def test_teacher_pay_mixes_generated_and_pending(
        self, school, teacher_user, student_user, management_user
    ):
        other_teacher = management_user  # any second user works as a batch teacher
        generated_batch = _batch(school, teacher_user)
        _item(generated_batch, student_user, 1, **self.RATES)
        _payroll_invoice(school, teacher_user, generated_batch, Decimal('45.00'))
        pending_batch = _batch(school, other_teacher)
        pending_item = _item(pending_batch, student_user, 8, **self.RATES)

        row = compute_month_rows(school, months=1, today=JUNE)[0]
        assert Decimal(row['teacher_pay_generated']) == Decimal('45.00')
        assert Decimal(row['teacher_pay_pending']) == pending_item.calculate_teacher_payment()
        assert Decimal(row['teacher_pay']) == (
            Decimal(row['teacher_pay_generated']) + Decimal(row['teacher_pay_pending'])
        )

    @pytest.mark.parametrize('batch_status', ['draft', 'submitted', 'rejected'])
    def test_teacher_pay_ignores_unapproved_batches(
        self, school, teacher_user, student_user, batch_status
    ):
        batch = _batch(school, teacher_user, status=batch_status)
        _item(batch, student_user, 1, **self.RATES)

        row = compute_month_rows(school, months=1, today=JUNE)[0]
        assert Decimal(row['teacher_pay']) == 0

    def test_teacher_pay_zero_for_unpaid_statuses(self, school, teacher_user, student_user):
        batch = _batch(school, teacher_user)
        for day, item_status in ((1, 'waived'), (8, 'cancelled'), (15, 'teacher_cancelled')):
            _item(batch, student_user, day, item_status, **self.RATES)

        row = compute_month_rows(school, months=1, today=JUNE)[0]
        assert Decimal(row['teacher_pay']) == 0

    def test_teacher_pay_respects_test_data_filter(
        self, school, teacher_user, student_user, settings
    ):
        settings.ANALYTICS_EXCLUDE_TEST_DATA = True
        settings.TEST_ACCOUNT_EMAIL_DOMAINS = ['maplekeytest.com']
        teacher_user.email = 'teach@maplekeytest.com'
        teacher_user.save(update_fields=['email'])
        batch = _batch(school, teacher_user)
        _item(batch, student_user, 1, **self.RATES)

        row = compute_month_rows(school, months=1, today=JUNE)[0]
        assert Decimal(row['teacher_pay']) == 0


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

    def test_listed_email_excluded_when_flag_on(self, school, active_schedule, settings):
        """MAP-218: an exact address in TEST_ACCOUNT_EMAILS is hidden like a test domain."""
        settings.ANALYTICS_EXCLUDE_TEST_DATA = True
        settings.TEST_ACCOUNT_EMAIL_DOMAINS = ['maplekeytest.com']
        settings.TEST_ACCOUNT_EMAILS = [
            active_schedule.student.email.upper(),   # case-insensitive match
            active_schedule.teacher.email,
        ]
        rows = compute_month_rows(school, months=1, today=JUNE)
        current = compute_current_metrics(school, today=JUNE)
        assert rows[0]['mrr'] == '0.00'
        assert current['active_teachers'] == 0

    def test_listed_email_included_when_flag_off(self, school, active_schedule, settings):
        settings.ANALYTICS_EXCLUDE_TEST_DATA = False
        settings.TEST_ACCOUNT_EMAILS = [
            active_schedule.student.email, active_schedule.teacher.email,
        ]
        rows = compute_month_rows(school, months=1, today=JUNE)
        current = compute_current_metrics(school, today=JUNE)
        assert rows[0]['mrr'] == '300.00'
        assert current['active_teachers'] == 1
