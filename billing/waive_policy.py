"""Waived-cancellation limit policy (MAP-101).

Students get a capped number of free (waived) cancellations per period —
past the cap, a teacher marking "waived" is recorded as forfeited instead
(student is charged, credit consumed by the usual forfeit flow). Management
edits are never converted: they are the override path.

Usage counting spans both live batch items (draft/submitted/approved batches
still holding BatchLessonItem rows) and Lesson records (items are deleted and
replaced by Lessons when a batch is approved) — so history survives approval.
"""

from datetime import date

from .models import BatchLessonItem, Lesson, SchoolSettings


def _shift_months(d, months):
    """d minus `months` months, clamped to the last valid day of the month."""
    month_index = d.year * 12 + (d.month - 1) - months
    year, month = divmod(month_index, 12)
    month += 1
    day = d.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


def _fixed_window_for(settings, on_date):
    """Resolve the fixed-dates window containing on_date, or None."""
    start, end = settings.waive_period_start, settings.waive_period_end
    if not start or not end:
        return None

    if not settings.waive_period_recurring:
        return (start, end) if start <= on_date <= end else None

    # Recurring: match by month/day, projected onto years around on_date.
    # Handles windows that span a year boundary (e.g. Sep 1 – Jan 31).
    for year_offset in (0, -1):
        year = on_date.year + year_offset
        window_start = start.replace(year=year)
        # Window end lands in a later year if the window wraps past Dec 31
        end_year = year + (1 if (end.month, end.day) < (start.month, start.day) else 0)
        window_end = end.replace(year=end_year)
        if window_start <= on_date <= window_end:
            return (window_start, window_end)
    return None


def get_waive_usage(student, school, on_date=None, exclude_item_id=None):
    """Waive usage for a student in the current policy period.

    Returns a dict: enabled, limit, used, remaining, period_start, period_end.
    When the policy is disabled or no fixed window is active, enabled=False
    and remaining is None (unlimited).
    """
    on_date = on_date or date.today()
    settings = SchoolSettings.get_settings_for_school(school)

    disabled = {
        'enabled': False,
        'limit': settings.waive_limit,
        'used': 0,
        'remaining': None,
        'period_start': None,
        'period_end': None,
    }
    if not settings.waive_limit_enabled:
        return disabled

    if settings.waive_period_type == 'rolling':
        period = (_shift_months(on_date, settings.waive_period_months), on_date)
    else:
        period = _fixed_window_for(settings, on_date)
        if period is None:
            return disabled

    start, end = period

    item_qs = BatchLessonItem.objects.filter(
        student=student,
        batch__school=school,
        status='waived',
        scheduled_date__gte=start,
        scheduled_date__lte=end,
    )
    if exclude_item_id is not None:
        item_qs = item_qs.exclude(pk=exclude_item_id)

    # Lesson.scheduled_date is a DateTimeField — compare on the date part
    lesson_count = Lesson.objects.filter(
        student=student,
        school=school,
        status='waived',
        scheduled_date__date__gte=start,
        scheduled_date__date__lte=end,
    ).count()

    used = item_qs.count() + lesson_count
    return {
        'enabled': True,
        'limit': settings.waive_limit,
        'used': used,
        'remaining': max(0, settings.waive_limit - used),
        'period_start': start.isoformat(),
        'period_end': end.isoformat(),
    }


def apply_waive_limit(update_data, student, school, exclude_item_id=None):
    """Convert a teacher's 'waived' to 'forfeited' when the limit is spent.

    Mutates and returns (update_data, usage, converted). Call ONLY on teacher
    paths — management edits are the override and must not pass through here.
    """
    if update_data.get('status') != 'waived':
        return update_data, None, False

    usage = get_waive_usage(student, school, exclude_item_id=exclude_item_id)
    if not usage['enabled'] or usage['remaining'] > 0:
        return update_data, usage, False

    update_data = dict(update_data)
    update_data['status'] = 'forfeited'
    note = (
        f"[Waive limit reached ({usage['used']}/{usage['limit']} used this period) "
        f"— recorded as forfeited]"
    )
    existing = (update_data.get('cancellation_reason') or '').strip()
    update_data['cancellation_reason'] = f"{existing} {note}".strip() if existing else note
    return update_data, usage, True
