"""MAP-101 — waived-cancellation limit.

Students get `waive_limit` free (waived) cancellations per period; past the
limit a TEACHER's "waived" is recorded as forfeited (student charged), with
the reason annotated. Management edits are the override path and are never
converted. Policy is off by default (waive_limit_enabled=False).
"""

import pytest
from datetime import date, time, timedelta
from decimal import Decimal
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from billing.models import (
    BatchLessonItem,
    Lesson,
    MonthlyInvoiceBatch,
    SchoolSettings,
)
from billing.waive_policy import get_waive_usage


TODAY = date.today()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def teacher_client(api_client, teacher_user):
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def management_client(api_client, management_user):
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.fixture
def policy_on(school, db):
    settings = SchoolSettings.get_settings_for_school(school)
    settings.waive_limit_enabled = True
    settings.waive_limit = 2
    settings.waive_period_type = 'rolling'
    settings.waive_period_months = 4
    settings.save()
    return settings


@pytest.fixture
def draft_batch(teacher_user, db):
    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=teacher_user.school,
        month=TODAY.month,
        year=TODAY.year,
        status='draft',
    )


def make_item(batch, student, day_offset=0, status='confirmed'):
    return BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=TODAY + timedelta(days=day_offset),
        start_time=time(15, 0),
        duration=Decimal('1.00'),
        lesson_type='in_person',
        teacher_rate=Decimal('40.00'),
        student_rate=Decimal('60.00'),
        status=status,
    )


def item_url(batch_id, item_id):
    return reverse('batch_lesson_item', kwargs={'batch_id': batch_id, 'item_id': item_id})


@pytest.mark.django_db
class TestWaiveUsageCounting:
    def test_counts_batch_items_and_lessons(self, policy_on, teacher_user, student_user, draft_batch):
        make_item(draft_batch, student_user, day_offset=-7, status='waived')
        Lesson.objects.create(
            school=teacher_user.school,
            teacher=teacher_user,
            student=student_user,
            scheduled_date=timezone.now() - timedelta(days=30),
            duration=Decimal('1.00'),
            lesson_type='in_person',
            teacher_rate=Decimal('40.00'),
            student_rate=Decimal('60.00'),
            status='waived',
        )
        usage = get_waive_usage(student_user, teacher_user.school)
        assert usage['enabled'] is True
        assert usage['used'] == 2
        assert usage['remaining'] == 0

    def test_future_dated_waives_count_in_rolling_window(
        self, policy_on, teacher_user, student_user, draft_batch
    ):
        # Waiving ahead with notice is the normal case — future waives must
        # count immediately or the limit is trivially bypassed (W2 UAT bug).
        make_item(draft_batch, student_user, day_offset=2, status='waived')
        make_item(draft_batch, student_user, day_offset=9, status='waived')
        usage = get_waive_usage(student_user, teacher_user.school)
        assert usage['used'] == 2
        assert usage['remaining'] == 0
        assert usage['period_end'] is None  # rolling window has no upper bound

    def test_approved_waive_counts_once_not_twice(
        self, policy_on, teacher_user, student_user, draft_batch
    ):
        # Approval creates a waived audit Lesson and links it to the item —
        # the pair must count as ONE waive (W2 UAT bug: 3 waives read as 6).
        item = make_item(draft_batch, student_user, day_offset=-7, status='waived')
        lesson = Lesson.objects.create(
            school=teacher_user.school,
            teacher=teacher_user,
            student=student_user,
            scheduled_date=timezone.now() - timedelta(days=7),
            duration=Decimal('1.00'),
            lesson_type='in_person',
            teacher_rate=Decimal('40.00'),
            student_rate=Decimal('60.00'),
            status='waived',
        )
        item.created_lesson = lesson
        item.save(update_fields=['created_lesson'])

        usage = get_waive_usage(student_user, teacher_user.school)
        assert usage['used'] == 1

    def test_adjustment_window_waive_counts_via_item(
        self, policy_on, teacher_user, student_user, draft_batch
    ):
        # Item waived AFTER approval: linked Lesson still says 'confirmed' —
        # the item row is the waive's only record and must count (audit #2).
        lesson = Lesson.objects.create(
            school=teacher_user.school,
            teacher=teacher_user,
            student=student_user,
            scheduled_date=timezone.now() - timedelta(days=7),
            duration=Decimal('1.00'),
            lesson_type='in_person',
            teacher_rate=Decimal('40.00'),
            student_rate=Decimal('60.00'),
            status='confirmed',
        )
        item = make_item(draft_batch, student_user, day_offset=-7, status='waived')
        item.created_lesson = lesson
        item.save(update_fields=['created_lesson'])

        usage = get_waive_usage(student_user, teacher_user.school)
        assert usage['used'] == 1

    def test_reasserting_approved_waive_does_not_self_convert(
        self, policy_on, teacher_user, student_user, teacher_client
    ):
        # Approved-waived item re-saved as 'waived' must exclude its own
        # linked waived Lesson from the count (audit #3) — otherwise a
        # granted waive silently flips to forfeited at the limit.
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user,
            school=teacher_user.school,
            month=TODAY.month,
            year=TODAY.year,
            status='approved',
        )
        lesson = Lesson.objects.create(
            school=teacher_user.school,
            teacher=teacher_user,
            student=student_user,
            scheduled_date=timezone.now() - timedelta(days=7),
            duration=Decimal('1.00'),
            lesson_type='in_person',
            teacher_rate=Decimal('40.00'),
            student_rate=Decimal('60.00'),
            status='waived',
        )
        item = make_item(batch, student_user, day_offset=-7, status='waived')
        item.created_lesson = lesson
        item.save(update_fields=['created_lesson'])
        # One more waive elsewhere puts the student AT the limit of 2
        Lesson.objects.create(
            school=teacher_user.school,
            teacher=teacher_user,
            student=student_user,
            scheduled_date=timezone.now() - timedelta(days=14),
            duration=Decimal('1.00'),
            lesson_type='in_person',
            teacher_rate=Decimal('40.00'),
            student_rate=Decimal('60.00'),
            status='waived',
        )

        url = reverse(
            'teacher_batch_adjustment_item',
            kwargs={'batch_id': batch.id, 'item_id': item.id},
        )
        response = teacher_client.patch(
            url, {'status': 'waived', 'cancellation_reason': 'edited note'}, format='json'
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.status == 'waived'  # NOT forfeited

    def test_fixed_window_anchored_to_lesson_date_not_today(
        self, school, teacher_user, student_user, teacher_client
    ):
        # December lesson adjusted in January must be judged against the
        # window CONTAINING the lesson, not today's window (audit #4).
        settings = SchoolSettings.get_settings_for_school(school)
        settings.waive_limit_enabled = True
        settings.waive_limit = 1
        settings.waive_period_type = 'fixed'
        # Recurring term ending ~2 months ago; lesson falls inside it
        term_end = TODAY - timedelta(days=60)
        term_start = term_end - timedelta(days=120)
        settings.waive_period_start = term_start
        settings.waive_period_end = term_end
        settings.waive_period_recurring = True
        settings.save()

        in_term_date = term_end - timedelta(days=10)
        # Student already used their 1 waive inside that term
        Lesson.objects.create(
            school=school,
            teacher=teacher_user,
            student=student_user,
            scheduled_date=timezone.now() - timedelta(days=70),
            duration=Decimal('1.00'),
            lesson_type='in_person',
            teacher_rate=Decimal('40.00'),
            student_rate=Decimal('60.00'),
            status='waived',
        )

        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user,
            school=school,
            month=in_term_date.month,
            year=in_term_date.year,
            status='approved',
        )
        item = BatchLessonItem.objects.create(
            batch=batch,
            student=student_user,
            scheduled_date=in_term_date,
            start_time=time(15, 0),
            duration=Decimal('1.00'),
            lesson_type='in_person',
            teacher_rate=Decimal('40.00'),
            student_rate=Decimal('60.00'),
            status='confirmed',
        )
        url = reverse(
            'teacher_batch_adjustment_item',
            kwargs={'batch_id': batch.id, 'item_id': item.id},
        )
        response = teacher_client.patch(url, {'status': 'waived'}, format='json')
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        # Judged against the lesson's term (limit already spent) → forfeited
        assert item.status == 'forfeited'

    def test_feb29_policy_dates_do_not_crash(self, school, teacher_user, student_user, db):
        settings = SchoolSettings.get_settings_for_school(school)
        settings.waive_limit_enabled = True
        settings.waive_period_type = 'fixed'
        settings.waive_period_start = date(2024, 2, 29)
        settings.waive_period_end = date(2024, 6, 30)
        settings.waive_period_recurring = True
        settings.save()
        # Must not raise in non-leap years (Feb 29 clamps to Feb 28)
        usage = get_waive_usage(student_user, school, on_date=date(2026, 3, 15))
        assert usage['enabled'] is True

    def test_recurring_window_longer_than_year_rejected(self, management_client):
        url = reverse('waive_policy_settings')
        response = management_client.put(
            url,
            {
                'waive_limit_enabled': True,
                'waive_period_type': 'fixed',
                'waive_period_start': '2025-06-01',
                'waive_period_end': '2026-08-31',
                'waive_period_recurring': True,
            },
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_disabled_policy_reports_unlimited(self, teacher_user, student_user, db):
        usage = get_waive_usage(student_user, teacher_user.school)
        assert usage['enabled'] is False
        assert usage['remaining'] is None

    def test_fixed_recurring_window(self, school, teacher_user, student_user, db):
        settings = SchoolSettings.get_settings_for_school(school)
        settings.waive_limit_enabled = True
        settings.waive_limit = 3
        settings.waive_period_type = 'fixed'
        # Window containing today, defined on an arbitrary past year
        start = (TODAY - timedelta(days=30)).replace(year=2020)
        end = (TODAY + timedelta(days=30)).replace(year=2020)
        settings.waive_period_start = start
        settings.waive_period_end = end
        settings.waive_period_recurring = True
        settings.save()

        usage = get_waive_usage(student_user, school)
        assert usage['enabled'] is True
        assert usage['period_start'] <= TODAY.isoformat() <= usage['period_end']


@pytest.mark.django_db
class TestTeacherWaiveConversion:
    def test_waive_within_limit_stays_waived(self, policy_on, teacher_client, student_user, draft_batch):
        item = make_item(draft_batch, student_user)
        response = teacher_client.put(
            item_url(draft_batch.id, item.id),
            {'status': 'waived', 'cancellation_reason': 'Sick'},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.status == 'waived'
        assert 'waive_converted_to_forfeited' not in response.data

    def test_waive_past_limit_becomes_forfeited(self, policy_on, teacher_client, student_user, draft_batch):
        make_item(draft_batch, student_user, day_offset=-14, status='waived')
        make_item(draft_batch, student_user, day_offset=-7, status='waived')
        item = make_item(draft_batch, student_user, day_offset=-1)

        response = teacher_client.put(
            item_url(draft_batch.id, item.id),
            {'status': 'waived', 'cancellation_reason': 'Sick again'},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['waive_converted_to_forfeited'] is True
        assert response.data['waive_usage']['used'] == 2
        item.refresh_from_db()
        assert item.status == 'forfeited'
        assert 'Waive limit reached' in item.cancellation_reason
        assert 'Sick again' in item.cancellation_reason

    def test_policy_disabled_no_conversion(self, teacher_client, student_user, draft_batch, db):
        make_item(draft_batch, student_user, day_offset=-14, status='waived')
        make_item(draft_batch, student_user, day_offset=-7, status='waived')
        item = make_item(draft_batch, student_user, day_offset=-1)

        response = teacher_client.put(
            item_url(draft_batch.id, item.id), {'status': 'waived'}, format='json'
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.status == 'waived'

    def test_retoggling_existing_waived_item_not_double_counted(
        self, policy_on, teacher_client, student_user, draft_batch
    ):
        # 2 waived = at limit, but one of them IS the item being re-saved —
        # excluding it leaves 1 used, so the re-save must stay waived.
        make_item(draft_batch, student_user, day_offset=-14, status='waived')
        item = make_item(draft_batch, student_user, day_offset=-7, status='waived')

        response = teacher_client.put(
            item_url(draft_batch.id, item.id), {'status': 'waived'}, format='json'
        )
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.status == 'waived'


@pytest.mark.django_db
class TestAdjustmentEndpointGuard:
    def test_future_waive_past_limit_refused(self, policy_on, teacher_client, student_user, teacher_user):
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user,
            school=teacher_user.school,
            month=TODAY.month,
            year=TODAY.year,
            status='approved',
        )
        make_item(batch, student_user, day_offset=-14, status='waived')
        make_item(batch, student_user, day_offset=-7, status='waived')
        future_item = make_item(batch, student_user, day_offset=5)

        url = reverse(
            'teacher_batch_adjustment_item',
            kwargs={'batch_id': batch.id, 'item_id': future_item.id},
        )
        response = teacher_client.patch(url, {'status': 'waived'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'Waive limit reached' in response.data['error']
        future_item.refresh_from_db()
        assert future_item.status == 'confirmed'


@pytest.mark.django_db
class TestWaiveEndpoints:
    def test_usage_endpoint(self, policy_on, teacher_client, student_user, draft_batch):
        make_item(draft_batch, student_user, day_offset=-7, status='waived')
        url = reverse('student_waive_usage', kwargs={'student_id': student_user.id})
        response = teacher_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['used'] == 1
        assert response.data['remaining'] == 1

    def test_policy_settings_get_and_put(self, management_client, school):
        url = reverse('waive_policy_settings')
        response = management_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['waive_limit_enabled'] is False

        response = management_client.put(
            url,
            {'waive_limit_enabled': True, 'waive_limit': 5, 'waive_period_months': 6},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        settings = SchoolSettings.get_settings_for_school(school)
        assert settings.waive_limit == 5
        assert settings.waive_limit_enabled is True

    def test_policy_settings_teacher_forbidden(self, teacher_client):
        url = reverse('waive_policy_settings')
        response = teacher_client.get(url)
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_fixed_period_requires_dates_when_enabled(self, management_client):
        url = reverse('waive_policy_settings')
        response = management_client.put(
            url,
            {'waive_limit_enabled': True, 'waive_period_type': 'fixed'},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
