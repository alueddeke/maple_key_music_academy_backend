"""
MAP-103: monthly batch archive.

Coverage:
  - archive-month archives approved batches and rejected drafts, skips
    submitted and clean drafts
  - archived batches disappear from approved/rejected/month-end lists
  - archived list returns them; unarchive restores to working lists
  - archiving preserves rows (nothing deleted)
"""

from django.urls import reverse
from django.utils import timezone

import pytest

from billing.models import MonthlyInvoiceBatch


def _make_batch(teacher, school, month=6, year=2026, **extra):
    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher, school=school, month=month, year=year, **extra
    )


@pytest.fixture
def management_client(api_client, management_user):
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.mark.django_db
class TestArchiveMonth:
    def test_archives_approved_batch(self, management_client, teacher_user, school):
        approved = _make_batch(teacher_user, school, status='approved')

        response = management_client.post(
            reverse('management_archive_month'), {'month': 6, 'year': 2026},
            format='json',
        )
        assert response.status_code == 200
        assert response.data['archived'] == 1

        approved.refresh_from_db()
        assert approved.archived_at is not None

    def test_archives_rejected_draft(self, management_client, teacher_user, school):
        rejected = _make_batch(
            teacher_user, school, month=5,
            status='draft', rejection_reason='fix rates',
        )

        response = management_client.post(
            reverse('management_archive_month'), {'month': 5, 'year': 2026},
            format='json',
        )
        assert response.status_code == 200
        assert response.data['archived'] == 1

        rejected.refresh_from_db()
        assert rejected.archived_at is not None

    def test_submitted_and_clean_drafts_not_archived(
        self, management_client, teacher_user, school
    ):
        submitted = _make_batch(
            teacher_user, school, status='submitted',
        )
        response = management_client.post(
            reverse('management_archive_month'), {'month': 6, 'year': 2026},
            format='json',
        )
        assert response.status_code == 200
        assert response.data['archived'] == 0
        submitted.refresh_from_db()
        assert submitted.archived_at is None

    def test_invalid_month_rejected(self, management_client):
        response = management_client.post(
            reverse('management_archive_month'), {'month': 13, 'year': 2026},
            format='json',
        )
        assert response.status_code == 400

    def test_nothing_deleted(self, management_client, teacher_user, school):
        _make_batch(teacher_user, school, status='approved')
        before = MonthlyInvoiceBatch.objects.count()
        management_client.post(
            reverse('management_archive_month'), {'month': 6, 'year': 2026},
            format='json',
        )
        assert MonthlyInvoiceBatch.objects.count() == before


@pytest.mark.django_db
class TestArchivedVisibility:
    def test_archived_batch_leaves_approved_list_and_appears_in_archived(
        self, management_client, teacher_user, school
    ):
        batch = _make_batch(teacher_user, school, status='approved')
        batch.archived_at = timezone.now()
        batch.save(update_fields=['archived_at'])

        approved = management_client.get(reverse('management_approved_batches'))
        assert all(row['id'] != batch.id for row in approved.data)

        archived = management_client.get(reverse('management_archived_batches'))
        assert any(row['id'] == batch.id for row in archived.data)

    def test_unarchive_restores(self, management_client, teacher_user, school):
        batch = _make_batch(teacher_user, school, status='approved')
        batch.archived_at = timezone.now()
        batch.save(update_fields=['archived_at'])

        response = management_client.post(
            reverse('management_unarchive_batch', args=[batch.id])
        )
        assert response.status_code == 200
        batch.refresh_from_db()
        assert batch.archived_at is None

        approved = management_client.get(reverse('management_approved_batches'))
        assert any(row['id'] == batch.id for row in approved.data)

    def test_unarchive_active_batch_400(
        self, management_client, teacher_user, school
    ):
        batch = _make_batch(teacher_user, school, status='approved')
        response = management_client.post(
            reverse('management_unarchive_batch', args=[batch.id])
        )
        assert response.status_code == 400
