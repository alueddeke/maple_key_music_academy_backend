"""
Unit tests for Phase 22 teacher adjustment status validation.

Coverage:
  - ADJ-03: Future lesson (scheduled_date > today) rejects completed/forfeited with 400
  - ADJ-03: Future lesson allows waived status
  - ADJ-03: Past lesson allows completed status

These tests are intentionally RED -- they reference the URL name
'teacher_batch_adjustment_item' which does not exist until Plan 02.
They MUST fail now (NoReverseMatch); that is the expected RED state.
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

    All tests in this class are RED until Plan 02 adds teacher_batch_adjustment_item
    URL + view implementing the date-based guard.
    """

    def test_future_lesson_rejects_completed_status(
        self, school, teacher_user, student_user, school_settings
    ):
        """
        ADJ-03: PATCH status='completed' on a future-dated item returns 400
        with 'Cannot mark future lesson' in response.data['error'].

        RED: NoReverseMatch until Plan 02 adds teacher_batch_adjustment_item.
        """
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
        """
        ADJ-03: PATCH status='forfeited' on a future-dated item returns 400.

        RED: NoReverseMatch until Plan 02 adds teacher_batch_adjustment_item.
        """
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
        """
        ADJ-03: PATCH status='waived' on a future-dated item is allowed and returns 200.
        (Waived = teacher cancelled in advance; valid for future dates.)

        RED: NoReverseMatch until Plan 02 adds teacher_batch_adjustment_item.
        """
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
        """
        ADJ-03 (inverse): PATCH status='completed' on a past-dated item is allowed.
        The date guard only rejects completed/forfeited for FUTURE lessons.

        RED: NoReverseMatch until Plan 02 adds teacher_batch_adjustment_item.
        """
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
