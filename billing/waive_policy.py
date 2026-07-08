"""Waived-cancellation limit policy (MAP-101).

Students get a capped number of free (waived) cancellations per period —
past the cap, a teacher marking "waived" is recorded as forfeited instead
(student is charged, credit consumed by the usual forfeit flow). Management
edits are never converted: they are the override path.

Usage counting spans both batch items and Lesson records. Approval writes a
waived audit Lesson and links it via created_lesson (the item row survives):
an approval-time waive counts once via the Lesson; an adjustment-window waive
(item waived AFTER approval, linked Lesson still says confirmed) counts once
via the item. Enforcement is anchored to the LESSON's date, not today — a
January adjustment to a December lesson is judged against December's window.
"""

from django.utils import timezone

from .models import BatchLessonItem, Lesson, SchoolSettings


def _shift_months(d, months):
    """d minus `months` months, clamped to the last valid day of the month."""
    from datetime import date
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


def _replace_year(d, year):
    """d projected onto `year`; Feb 29 clamps to Feb 28 in non-leap years."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


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
        window_start = _replace_year(start, year)
        # Window end lands in a later year if the window wraps past Dec 31
        end_year = year + (1 if (end.month, end.day) < (start.month, start.day) else 0)
        window_end = _replace_year(end, end_year)
        if window_start <= on_date <= window_end:
            return (window_start, window_end)
    return None


def get_waive_usage(
    student,
    school,
    on_date=None,
    exclude_item_id=None,
    exclude_lesson_id=None,
):
    """Waive usage for a student in the policy period containing on_date.

    on_date should be the date of the lesson being judged (defaults to today
    for informational queries). exclude_item_id / exclude_lesson_id drop the
    record(s) belonging to the lesson currently being edited so re-saving an
    already-waived lesson doesn't count against itself.

    Returns a dict: enabled, limit, used, remaining, period_start, period_end.
    When the policy is disabled or no fixed window contains on_date,
    enabled=False and remaining is None (unlimited).
    """
    on_date = on_date or timezone.localdate()
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
        # No upper bound: teachers waive future lessons ahead of time (proper
        # notice IS the waive case), so future-dated waives count immediately —
        # otherwise a student could bank unlimited waives for upcoming lessons.
        period = (_shift_months(on_date, settings.waive_period_months), None)
    else:
        period = _fixed_window_for(settings, on_date)
        if period is None:
            return disabled

    start, end = period

    # Item-side count. Excluding items whose linked Lesson is ALSO waived
    # avoids double counting approval-time waives (those count via the Lesson);
    # items waived in the adjustment window (linked Lesson still 'confirmed')
    # are kept — the item row is their only record.
    item_qs = BatchLessonItem.objects.filter(
        student=student,
        batch__school=school,
        status='waived',
        scheduled_date__gte=start,
    ).exclude(created_lesson__status='waived')
    if end is not None:
        item_qs = item_qs.filter(scheduled_date__lte=end)
    if exclude_item_id is not None:
        item_qs = item_qs.exclude(pk=exclude_item_id)

    # Lesson.scheduled_date is a DateTimeField — compare on the date part
    lesson_qs = Lesson.objects.filter(
        student=student,
        school=school,
        status='waived',
        scheduled_date__date__gte=start,
    )
    if end is not None:
        lesson_qs = lesson_qs.filter(scheduled_date__date__lte=end)
    if exclude_lesson_id is not None:
        lesson_qs = lesson_qs.exclude(pk=exclude_lesson_id)
    lesson_count = lesson_qs.count()

    used = item_qs.count() + lesson_count
    return {
        'enabled': True,
        'limit': settings.waive_limit,
        'used': used,
        'remaining': max(0, settings.waive_limit - used),
        'period_start': start.isoformat(),
        'period_end': end.isoformat() if end is not None else None,
    }


def apply_waive_limit(update_data, student, school, item=None):
    """Convert a teacher's 'waived' to 'forfeited' when the limit is spent.

    `item` is the BatchLessonItem being edited: its date anchors the policy
    period, and its own prior waive records (the item and any linked Lesson)
    are excluded from the count. Mutates and returns
    (update_data, usage, converted). Call ONLY on teacher paths — management
    edits are the override and must not pass through here.
    """
    if update_data.get('status') != 'waived':
        return update_data, None, False

    usage = get_waive_usage(
        student,
        school,
        on_date=item.scheduled_date if item is not None else None,
        exclude_item_id=item.id if item is not None else None,
        exclude_lesson_id=item.created_lesson_id if item is not None else None,
    )
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
