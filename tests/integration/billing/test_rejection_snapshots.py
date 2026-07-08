"""MAP-99 — rejected batches must be preserved as they were when rejected.

Rejection flips the batch back to draft (teacher edits + resubmits), so a
BatchRejectionSnapshot freezes the line items at the moment of rejection.
"""

import pytest
from datetime import date, time
from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from billing.models import (
    BatchLessonItem,
    BatchRejectionSnapshot,
    MonthlyInvoiceBatch,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def authenticated_management_client(api_client, management_user):
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.fixture
def authenticated_teacher_client(api_client, teacher_user):
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def submitted_batch(teacher_user, student_user, db):
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=teacher_user,
        school=teacher_user.school,
        month=7,
        year=2026,
        status='submitted',
    )
    BatchLessonItem.objects.create(
        batch=batch,
        student=student_user,
        scheduled_date=date(2026, 7, 2),
        start_time=time(15, 0),
        duration=Decimal('1.00'),
        lesson_type='in_person',
        teacher_rate=Decimal('40.00'),
        student_rate=Decimal('60.00'),
        status='completed',
    )
    return batch


def reject_url(batch_id):
    return reverse('management_reject_batch', args=[batch_id])


def snapshots_url(batch_id):
    return reverse('management_batch_rejection_snapshots', args=[batch_id])


@pytest.mark.django_db
class TestRejectionSnapshot:
    def test_reject_creates_snapshot(
        self, authenticated_management_client, submitted_batch, management_user
    ):
        response = authenticated_management_client.post(
            reject_url(submitted_batch.id),
            {'rejection_reason': 'Wrong dates'},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK

        snapshot = BatchRejectionSnapshot.objects.get(batch=submitted_batch)
        assert snapshot.rejection_reason == 'Wrong dates'
        assert snapshot.rejected_by == management_user
        assert len(snapshot.items) == 1
        assert snapshot.items[0]['scheduled_date'] == '2026-07-02'
        assert snapshot.total_teacher_payment == Decimal('40.00')

    def test_snapshot_survives_later_batch_changes(
        self, authenticated_management_client, submitted_batch, student_user
    ):
        authenticated_management_client.post(
            reject_url(submitted_batch.id),
            {'rejection_reason': 'Missing lessons'},
            format='json',
        )

        # Simulate what bit Bill: schedule-sync stuffs the (now draft) batch
        # with new lessons after rejection.
        BatchLessonItem.objects.create(
            batch=submitted_batch,
            student=student_user,
            scheduled_date=date(2026, 7, 9),
            start_time=time(15, 0),
            duration=Decimal('1.00'),
            lesson_type='in_person',
            teacher_rate=Decimal('40.00'),
            student_rate=Decimal('60.00'),
            status='confirmed',
        )

        snapshot = BatchRejectionSnapshot.objects.get(batch=submitted_batch)
        assert len(snapshot.items) == 1  # still exactly what was rejected

    def test_multiple_rejections_multiple_snapshots(
        self, authenticated_management_client, submitted_batch
    ):
        authenticated_management_client.post(
            reject_url(submitted_batch.id), {'rejection_reason': 'First'}, format='json'
        )
        submitted_batch.status = 'submitted'
        submitted_batch.save()
        authenticated_management_client.post(
            reject_url(submitted_batch.id), {'rejection_reason': 'Second'}, format='json'
        )

        reasons = list(
            BatchRejectionSnapshot.objects.filter(batch=submitted_batch)
            .order_by('rejected_at')
            .values_list('rejection_reason', flat=True)
        )
        assert reasons == ['First', 'Second']

    def test_snapshots_endpoint_returns_newest_first(
        self, authenticated_management_client, submitted_batch
    ):
        authenticated_management_client.post(
            reject_url(submitted_batch.id), {'rejection_reason': 'First'}, format='json'
        )
        submitted_batch.status = 'submitted'
        submitted_batch.save()
        authenticated_management_client.post(
            reject_url(submitted_batch.id), {'rejection_reason': 'Second'}, format='json'
        )

        response = authenticated_management_client.get(snapshots_url(submitted_batch.id))
        assert response.status_code == status.HTTP_200_OK
        assert [s['rejection_reason'] for s in response.data] == ['Second', 'First']
        assert response.data[0]['rejected_by_name']

    def test_snapshots_endpoint_teacher_forbidden(
        self, authenticated_teacher_client, submitted_batch
    ):
        response = authenticated_teacher_client.get(snapshots_url(submitted_batch.id))
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
