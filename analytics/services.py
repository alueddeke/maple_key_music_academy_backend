"""Read-only metric aggregation over billing data.

Every formula here is documented in .planning/fable-triage/MAP-38-KICKOFF.md.
This module NEVER writes to billing tables. Money math is Decimal throughout.

Definitions locked with product (2026-07-06):
- MRR = scheduled revenue (active schedules × locked student_rate × lessons that month).
- Churn(M) = active in M-1, now deactivated OR without any active schedule. Pause ≠ churn.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Min, Sum
from django.utils import timezone

from billing.models import (
    CreditTransaction,
    Invoice,
    Lesson,
    MonthlyInvoiceBatch,
    PreBillingInvoice,
    RecurringLessonsSchedule,
    SchoolExpenseItem,
    StudentInvoice,
)

from .models import MetricGoal, ScheduleInstrument, StudentExitRecord

User = get_user_model()

# Average weeks per month, used to project weekly availability to a month
WEEKS_PER_MONTH = Decimal('4.33')

# Window (months) for CPA: advertising spend ÷ new enrollments
CPA_WINDOW_MONTHS = 6


def _test_data_filter_active():
    """MAP-113: True when analytics should hide test-account rows (prod)."""
    return bool(
        getattr(settings, 'ANALYTICS_EXCLUDE_TEST_DATA', False)
        and getattr(settings, 'TEST_ACCOUNT_EMAIL_DOMAINS', [])
    )


def _exclude_test(qs, email_field):
    """
    Exclude rows whose linked account email belongs to a test domain.

    No-op unless ANALYTICS_EXCLUDE_TEST_DATA is enabled, so dev/UAT
    dashboards still show test data. `email_field` is the ORM path to the
    account email, e.g. 'student__email' or 'teacher__email'.
    """
    if not _test_data_filter_active():
        return qs
    for domain in settings.TEST_ACCOUNT_EMAIL_DOMAINS:
        qs = qs.exclude(**{f'{email_field}__iendswith': f'@{domain}'})
    return qs


def _month_starts(today, months):
    """Last `months` month-start dates, oldest first, ending at today's month."""
    anchor = today.replace(day=1)
    result = []
    year, month = anchor.year, anchor.month
    for _ in range(months):
        result.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return list(reversed(result))


def _prev_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _scheduled_hours_and_revenue(schedules, year, month):
    """(total lesson-hours, total scheduled revenue) for a month, per formulas."""
    hours = Decimal('0')
    revenue = Decimal('0')
    for schedule in schedules:
        lesson_count = len(schedule.generate_lessons_for_month(year, month))
        if lesson_count == 0:
            continue
        duration = Decimal(str(schedule.duration))
        hours += lesson_count * duration
        revenue += lesson_count * duration * Decimal(str(schedule.student_rate))
    return hours, revenue


def _first_lesson_by_student(school):
    """{student_id: first lesson date} across all time."""
    rows = (
        _exclude_test(Lesson.objects.filter(school=school), 'student__email')
        .values('student_id')
        .annotate(first=Min('scheduled_date'), last=Max('scheduled_date'))
    )
    return {r['student_id']: (r['first'], r['last']) for r in rows}


def _currently_churned_student_ids(school):
    """Students who are deactivated OR have zero active schedules (churn def)."""
    students = _exclude_test(
        User.objects.filter(school=school, user_type='student'), 'email'
    )
    with_active_schedule = set(
        RecurringLessonsSchedule.objects.filter(
            school=school, is_active=True
        ).values_list('student_id', flat=True)
    )
    return {
        s.id for s in students
        if (not s.is_active) or (s.id not in with_active_schedule)
    }


def compute_month_rows(school, months=6, today=None):
    """Trend table: one row per month, oldest first."""
    today = today or timezone.localdate()
    active_schedules = list(
        _exclude_test(
            RecurringLessonsSchedule.objects.filter(school=school, is_active=True),
            'student__email',
        ).select_related('student')
    )
    lesson_bounds = _first_lesson_by_student(school)
    churned_now = _currently_churned_student_ids(school)

    rows = []
    prev_active_count = None
    for month_start in _month_starts(today, months + 1):
        year, month = month_start.year, month_start.month

        _, mrr = _scheduled_hours_and_revenue(active_schedules, year, month)

        billed = _exclude_test(
            StudentInvoice.objects.filter(
                school=school, batch__year=year, batch__month=month
            ),
            'student__email',
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        expenses = SchoolExpenseItem.objects.filter(
            school=school,
            period_start__year=year,
            period_start__month=month,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        teacher_pay = _exclude_test(
            Invoice.objects.filter(
                school=school,
                invoice_type='teacher_payment',
                source_batch__year=year,
                source_batch__month=month,
            ),
            'teacher__email',
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

        active_students = (
            _exclude_test(
                StudentInvoice.objects.filter(
                    school=school, batch__year=year, batch__month=month
                ),
                'student__email',
            ).values('student_id').distinct().count()
        )

        new_enrollments = sum(
            1 for first, _ in lesson_bounds.values()
            if first and first.year == year and first.month == month
        )

        # Churned in M: last-ever lesson fell in M-1 AND currently churned
        prev_year, prev_mon = _prev_month(year, month)
        churned = sum(
            1 for student_id, (_, last) in lesson_bounds.items()
            if last and last.year == prev_year and last.month == prev_mon
            and student_id in churned_now
        )
        churn_rate = (
            round(churned / prev_active_count * 100, 1)
            if prev_active_count else None
        )

        cancelled_lessons = _exclude_test(
            Lesson.objects.filter(
                school=school,
                status='cancelled',
                scheduled_date__year=year,
                scheduled_date__month=month,
            ),
            'student__email',
        ).count()
        credit_counts = dict(
            _exclude_test(
                CreditTransaction.objects.filter(
                    school=school,
                    created_at__year=year,
                    created_at__month=month,
                    type__in=['forfeited', 'waived_rollover'],
                ),
                'account__student__email',
            ).values_list('type').annotate(n=Count('id'))
        )

        rows.append({
            'period': f'{year}-{month:02d}',
            'mrr': str(mrr.quantize(Decimal('0.01'))),
            'billed_revenue': str(billed),
            'expenses': str(expenses),
            'teacher_pay': str(teacher_pay),
            'gross_margin': str(billed - teacher_pay - expenses),
            'active_students': active_students,
            'new_enrollments': new_enrollments,
            'churned': churned,
            'churn_rate': churn_rate,
            'cancelled_lessons': cancelled_lessons,
            'cancellations_forfeited': credit_counts.get('forfeited', 0),
            'cancellations_waived': credit_counts.get('waived_rollover', 0),
        })
        prev_active_count = active_students

    # Drop the extra oldest row (only computed to seed prev_active_count)
    return rows[1:]


def _utilization_rate(school, active_schedules, today):
    """Scheduled hours ÷ available hours. None until teacher_profiles (MAP-30) merges."""
    if not apps.is_installed('teacher_profiles'):
        return None
    TeacherAvailability = apps.get_model('teacher_profiles', 'TeacherAvailability')

    weekly_seconds = 0
    for slot in TeacherAvailability.objects.filter(profile__school=school):
        start = timedelta(hours=slot.start_time.hour, minutes=slot.start_time.minute)
        end = timedelta(hours=slot.end_time.hour, minutes=slot.end_time.minute)
        weekly_seconds += (end - start).total_seconds()
    if weekly_seconds == 0:
        return None

    available_hours = Decimal(str(weekly_seconds / 3600)) * WEEKS_PER_MONTH
    scheduled_hours, _ = _scheduled_hours_and_revenue(
        active_schedules, today.year, today.month
    )
    return round(float(scheduled_hours / available_hours * 100), 1)


def compute_current_metrics(school, today=None):
    """Point-in-time metrics for the current state of the school."""
    today = today or timezone.localdate()
    active_schedules = list(
        _exclude_test(
            RecurringLessonsSchedule.objects.filter(school=school, is_active=True),
            'student__email',
        ).select_related('student')
    )

    active_student_ids = {
        s.student_id for s in active_schedules if s.student.is_active
    }
    active_students = len(active_student_ids)
    active_teachers = _exclude_test(
        User.objects.filter(
            school=school, user_type='teacher', is_active=True, is_approved=True
        ),
        'email',
    ).count()

    _, current_mrr = _scheduled_hours_and_revenue(
        active_schedules, today.year, today.month
    )

    # Duration mix across active schedules (hours → minutes label)
    duration_mix = Counter(
        f'{int(Decimal(str(s.duration)) * 60)} min' for s in active_schedules
    )

    # Revenue by instrument (scheduled revenue, grouped by side-table tag)
    instrument_map = dict(
        ScheduleInstrument.objects.filter(
            schedule__school=school
        ).values_list('schedule_id', 'instrument')
    )
    by_instrument = defaultdict(Decimal)
    for schedule in active_schedules:
        lesson_count = len(
            schedule.generate_lessons_for_month(today.year, today.month)
        )
        revenue = (
            lesson_count
            * Decimal(str(schedule.duration))
            * Decimal(str(schedule.student_rate))
        )
        label = instrument_map.get(schedule.id, 'Uncategorized')
        by_instrument[label] += revenue
    revenue_by_instrument = [
        {'instrument': k, 'amount': str(v.quantize(Decimal('0.01')))}
        for k, v in sorted(by_instrument.items(), key=lambda kv: -kv[1])
    ]

    # Tenure: months between first lesson and last lesson (active → today)
    lesson_bounds = _first_lesson_by_student(school)
    churned_now = _currently_churned_student_ids(school)
    tenures = []
    for student_id, (first, last) in lesson_bounds.items():
        if not first:
            continue
        end = last if student_id in churned_now else today
        first_d = first.date() if hasattr(first, 'date') else first
        end_d = end.date() if hasattr(end, 'date') else end
        tenures.append(max((end_d - first_d).days, 0) / 30.44)
    avg_tenure = round(sum(tenures) / len(tenures), 1) if tenures else None

    revenue_per_student = (
        (current_mrr / active_students).quantize(Decimal('0.01'))
        if active_students else None
    )
    ltv = (
        (revenue_per_student * Decimal(str(avg_tenure))).quantize(Decimal('0.01'))
        if revenue_per_student is not None and avg_tenure is not None else None
    )

    # Trial → enroll conversion (all-time)
    trial_students = set(
        _exclude_test(
            Lesson.objects.filter(school=school, is_trial=True), 'student__email'
        ).values_list('student_id', flat=True)
    )
    converted = set(
        Lesson.objects.filter(
            school=school, is_trial=False, student_id__in=trial_students
        ).values_list('student_id', flat=True)
    )
    trial_conversion = (
        round(len(converted) / len(trial_students) * 100, 1)
        if trial_students else None
    )

    # CPA: advertising expenses ÷ new enrollments over the window
    window_start = _month_starts(today, CPA_WINDOW_MONTHS)[0]
    ad_spend = SchoolExpenseItem.objects.filter(
        school=school,
        period_start__gte=window_start,
        category_tag__category='advertising',
    ).aggregate(total=Sum('amount'))['total']
    new_in_window = sum(
        1 for first, _ in lesson_bounds.values()
        if first and (first.date() if hasattr(first, 'date') else first) >= window_start
    )
    cpa = (
        (ad_spend / new_in_window).quantize(Decimal('0.01'))
        if ad_spend and new_in_window else None
    )
    ltv_cpa_ratio = (
        round(float(ltv / cpa), 1) if ltv is not None and cpa else None
    )

    # Overdue: unpaid pre-billing invoices past period_end + payment terms
    overdue_cutoff = today - timedelta(days=school.payment_terms_days or 0)
    overdue_qs = _exclude_test(
        PreBillingInvoice.objects.filter(
            school=school,
            period_end__lt=overdue_cutoff,
        ),
        'student__email',
    ).exclude(status='paid')
    overdue = overdue_qs.aggregate(total=Sum('amount'), n=Count('id'))

    exit_reasons = [
        {'reason': r['reason'], 'count': r['n']}
        for r in _exclude_test(
            StudentExitRecord.objects.filter(school=school), 'student__email'
        ).values('reason').annotate(n=Count('id')).order_by('-n')
    ]

    return {
        'mrr': str(current_mrr.quantize(Decimal('0.01'))),
        'active_students': active_students,
        'active_teachers': active_teachers,
        'student_teacher_ratio': (
            round(active_students / active_teachers, 1) if active_teachers else None
        ),
        'utilization_rate': _utilization_rate(school, active_schedules, today),
        'duration_mix': dict(duration_mix),
        'revenue_per_student': (
            str(revenue_per_student) if revenue_per_student is not None else None
        ),
        'revenue_by_instrument': revenue_by_instrument,
        'avg_tenure_months': avg_tenure,
        'ltv': str(ltv) if ltv is not None else None,
        'cpa': str(cpa) if cpa is not None else None,
        'ltv_cpa_ratio': ltv_cpa_ratio,
        'trial_conversion_rate': trial_conversion,
        'overdue_invoices': {
            'count': overdue['n'] or 0,
            'amount': str(overdue['total'] or Decimal('0')),
        },
        'exit_reasons': exit_reasons,
    }


def compute_goals(school, month_rows, current):
    """Resolve each saved goal against its live metric value."""
    latest = month_rows[-1] if month_rows else {}
    live_values = {
        'mrr': current.get('mrr'),
        'gross_margin': latest.get('gross_margin'),
        'active_students': current.get('active_students'),
        'new_enrollments': latest.get('new_enrollments'),
        'churn_rate': latest.get('churn_rate'),
        'trial_conversion': current.get('trial_conversion_rate'),
    }
    return [
        {
            'metric': goal.metric,
            'metric_display': goal.get_metric_display(),
            'target': str(goal.target),
            'current_value': (
                str(live_values[goal.metric])
                if live_values.get(goal.metric) is not None else None
            ),
        }
        for goal in MetricGoal.objects.filter(school=school).order_by('metric')
    ]


def compute_overview(school, months=6, today=None):
    month_rows = compute_month_rows(school, months=months, today=today)
    current = compute_current_metrics(school, today=today)
    return {
        'months': month_rows,
        'current': current,
        'goals': compute_goals(school, month_rows, current),
    }
