"""
Unit tests for Phase 22 teacher adjustment status validation
and Phase 25 reschedule-in-place functionality.

Coverage:
  - ADJ-03: Future lesson (scheduled_date > today) rejects completed/forfeited with 400
  - ADJ-03: Future lesson allows waived status
  - ADJ-03: Past lesson allows completed status
  - Phase 25 D-01: In-month reschedule accepted, out-of-month rejected
  - Phase 25 D-02: Reschedule keeps status and teacher_payment unchanged
  - Phase 25 D-02: Reschedule appends [Rescheduled] audit note
  - Phase 25 D-03: Locked batch rejects reschedule
  - Phase 25: Regression - forfeited/waived PATCH still works
"""

import pytest
from decimal import Decimal
from datetime import date, time, timedelta
from django.urls import reverse
from rest_framework.test import APIClient

from billing.models import (
    BatchLessonItem,
    MonthlyInvoiceBatch,
)


# ---------------------------------------------------------------------------
# Factory helpers (copied and adapted from test_batch_credit.py)
# ---------------------------------------------------------------------------

def _make_batch(teacher, school, batch_number=None, month=6, year=2026):
    """Create a MonthlyInvoiceBatch; auto-generates batch_number if not provided."""
    kwargs = dict(teacher=teacher, school=school, month=month, year=year)
    if batch_number:
        kwargs['batch_number'] = batch_number
    return MonthlyInvoiceBatch.objects.create(**kwargs)


def _make_batch_lesson_item(
    batch,
    student,
    status='completed',
    teacher_rate=Decimal('45.00'),
    student_rate=Decimal('60.00'),
    duration=Decimal('1.0'),
    scheduled_date=date(2026, 6, 15),
):
    """Create a BatchLessonItem with explicit sentinel rates and configurable scheduled_date.

    The scheduled_date parameter (default: 2026-06-15) allows future/past date tests:
    - Pass date.today() + timedelta(days=1) for a future lesson (ADJ-03 tests)
    - Pass date.today() - timedelta(days=1) for a past lesson
    """
    return BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=scheduled_date,
        start_time=time(10, 0),
        duration=duration,
        lesson_type='online',
        teacher_rate=teacher_rate,
        student_rate=student_rate,
        status=status,
    )


def _get_teacher_client(teacher_user):
    """Create APIClient authenticated as teacher_user."""
    client = APIClient()
    client.force_authenticate(user=teacher_user)
    return client


# ---------------------------------------------------------------------------
# Class 1 -- ADJ-03: Future lesson status validation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAdjStatusRulesFutureLessons:
    """ADJ-03: Future lesson (scheduled_date > today) status validation rules.

    The server must reject 'completed' and 'forfeited' for future-dated items,
    but allow 'waived'. Past-dated items may receive any status including 'completed'.
    """

    def test_future_lesson_rejects_completed_status(
        self, school, teacher_user, student_user, school_settings
    ):
        """ADJ-03: PATCH status='completed' on a future-dated item returns 400."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-22-01-ADJ-F1')
        batch.status = 'approved'
        batch.save()

        tomorrow = date.today() + timedelta(days=1)
        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=tomorrow,
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'status': 'completed'}, format='json')

        assert response.status_code == 400
        assert 'Cannot mark future lesson' in response.data.get('error', '')

    def test_future_lesson_rejects_forfeited_status(
        self, school, teacher_user, student_user, school_settings
    ):
        """ADJ-03: PATCH status='forfeited' on a future-dated item returns 400."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-22-01-ADJ-F2')
        batch.status = 'approved'
        batch.save()

        tomorrow = date.today() + timedelta(days=1)
        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=tomorrow,
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'status': 'forfeited'}, format='json')

        assert response.status_code == 400

    def test_future_lesson_allows_waived_status(
        self, school, teacher_user, student_user, school_settings
    ):
        """ADJ-03: PATCH status='waived' on a future-dated item is allowed and returns 200."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-22-01-ADJ-F3')
        batch.status = 'approved'
        batch.save()

        tomorrow = date.today() + timedelta(days=1)
        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=tomorrow,
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'status': 'waived'}, format='json')

        assert response.status_code == 200

    def test_past_lesson_allows_completed_status(
        self, school, teacher_user, student_user, school_settings
    ):
        """ADJ-03 (inverse): PATCH status='completed' on a past-dated item is allowed."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-22-01-ADJ-P1')
        batch.status = 'approved'
        batch.save()

        yesterday = date.today() - timedelta(days=1)
        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=yesterday,
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'status': 'completed'}, format='json')

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Class 2 -- Phase 25: Reschedule-in-place (scheduled_date/start_time)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRescheduleAdjustment:
    """Phase 25: Teacher can reschedule a lesson in place during the adjustment window.

    Covers:
    - In-month reschedule accepted (200, date updated)
    - Out-of-month reject — different month (400)
    - Out-of-month reject — same month number, different year (400)
    - Status and teacher_payment unchanged after reschedule
    - Locked batch (invoice_id set) rejects reschedule (400)
    - start_time updated alongside scheduled_date (200)
    - [Rescheduled] audit note appended to teacher_notes
    - Invalid date format returns 400
    - Regression: existing forfeited/waived PATCH still works
    """

    def test_reschedule_in_month_returns_200_and_updates_date(
        self, school, teacher_user, student_user, school_settings
    ):
        """PATCH scheduled_date to an in-month date on approved+un-invoiced batch -> 200, date updated."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-01', month=6, year=2026)
        batch.status = 'approved'
        batch.save()

        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 10),
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'scheduled_date': '2026-06-20'}, format='json')

        assert response.status_code == 200
        item.refresh_from_db()
        assert item.scheduled_date == date(2026, 6, 20)

    def test_reschedule_out_of_month_different_month_returns_400(
        self, school, teacher_user, student_user, school_settings
    ):
        """PATCH scheduled_date to a date in a different month -> 400."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-02', month=6, year=2026)
        batch.status = 'approved'
        batch.save()

        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 10),
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'scheduled_date': '2026-07-10'}, format='json')

        assert response.status_code == 400
        assert 'billing month' in response.data.get('error', '').lower()

    def test_reschedule_out_of_year_returns_400(
        self, school, teacher_user, student_user, school_settings
    ):
        """PATCH scheduled_date to a date in the same month number but different year -> 400."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-03', month=6, year=2026)
        batch.status = 'approved'
        batch.save()

        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 10),
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        # Same month number (6) but wrong year
        response = client.patch(url, {'scheduled_date': '2027-06-10'}, format='json')

        assert response.status_code == 400

    def test_reschedule_keeps_status_and_teacher_payment_unchanged(
        self, school, teacher_user, student_user, school_settings
    ):
        """PATCH scheduled_date alone keeps status=='confirmed' and teacher_payment unchanged (D-02)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-04', month=6, year=2026)
        batch.status = 'approved'
        batch.save()

        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 10),
            teacher_rate=Decimal('45.00'),
            duration=Decimal('1.0'),
        )
        original_payment = item.calculate_teacher_payment()

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'scheduled_date': '2026-06-15'}, format='json')

        assert response.status_code == 200
        item.refresh_from_db()
        assert item.status == 'confirmed'
        assert item.calculate_teacher_payment() == original_payment

    def test_reschedule_locked_batch_returns_400(
        self, school, teacher_user, student_user, school_settings
    ):
        """PATCH scheduled_date on a locked batch (invoice_id set) -> 400 (locked guard fires)."""
        from billing.models import Invoice

        # Create a minimal Invoice for the FK
        invoice = Invoice.objects.create(
            school=school,
            invoice_type='teacher_payment',
            teacher=teacher_user,
            payment_balance=Decimal('45.00'),
        )

        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-05', month=6, year=2026)
        batch.status = 'approved'
        batch.invoice = invoice
        batch.save()

        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 10),
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'scheduled_date': '2026-06-20'}, format='json')

        assert response.status_code == 400
        assert 'locked' in response.data.get('error', '').lower()

    def test_reschedule_updates_start_time_alongside_date(
        self, school, teacher_user, student_user, school_settings
    ):
        """PATCH scheduled_date + start_time together — both persist (200)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-06', month=6, year=2026)
        batch.status = 'approved'
        batch.save()

        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 10),
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(
            url,
            {'scheduled_date': '2026-06-22', 'start_time': '14:30:00'},
            format='json',
        )

        assert response.status_code == 200
        item.refresh_from_db()
        assert item.scheduled_date == date(2026, 6, 22)
        assert item.start_time.hour == 14
        assert item.start_time.minute == 30

    def test_reschedule_appends_audit_note(
        self, school, teacher_user, student_user, school_settings
    ):
        """After reschedule, item.teacher_notes contains '[Rescheduled]' audit line."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-07', month=6, year=2026)
        batch.status = 'approved'
        batch.save()

        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 10),
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'scheduled_date': '2026-06-18'}, format='json')

        assert response.status_code == 200
        item.refresh_from_db()
        assert '[Rescheduled]' in item.teacher_notes

    def test_reschedule_invalid_date_format_returns_400(
        self, school, teacher_user, student_user, school_settings
    ):
        """PATCH scheduled_date with a non-ISO-date string -> 400 with 'date' in error."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-08', month=6, year=2026)
        batch.status = 'approved'
        batch.save()

        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 10),
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'scheduled_date': 'not-a-date'}, format='json')

        assert response.status_code == 400
        assert 'date' in response.data.get('error', '').lower()

    def test_regression_forfeited_patch_still_works(
        self, school, teacher_user, student_user, school_settings
    ):
        """Regression: existing status='forfeited' PATCH is unchanged by reschedule extension."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-09', month=6, year=2026)
        batch.status = 'approved'
        batch.save()

        # Past date so future-lesson guard doesn't fire
        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 5),
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'status': 'forfeited'}, format='json')

        assert response.status_code == 200
        item.refresh_from_db()
        assert item.status == 'forfeited'

    def test_regression_waived_patch_still_works(
        self, school, teacher_user, student_user, school_settings
    ):
        """Regression: existing status='waived' PATCH is unchanged by reschedule extension."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-25-RS-10', month=6, year=2026)
        batch.status = 'approved'
        batch.save()

        item = _make_batch_lesson_item(
            batch, student_user,
            status='confirmed',
            scheduled_date=date(2026, 6, 10),
        )

        client = _get_teacher_client(teacher_user)
        url = reverse('teacher_batch_adjustment_item', kwargs={'batch_id': batch.id, 'item_id': item.id})

        response = client.patch(url, {'status': 'waived'}, format='json')

        assert response.status_code == 200
        item.refresh_from_db()
        assert item.status == 'waived'
