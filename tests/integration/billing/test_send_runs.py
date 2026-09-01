"""
Integration tests for the invoice send-run endpoints (batch-queue wave).

Covers the enqueue lifecycle only — the worker that drains runs is tested in
test_send_run_worker.py. Contract under test:
- send-all snapshots drafts at click time (cutoff), 202 + run
- one live run per school+period (409 carries the live run id)
- detail/latest/cancel are school-isolated
"""
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from billing.models import InvoiceSendRun, PreBillingInvoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def management_client(management_user):
    client = APIClient()
    client.force_authenticate(user=management_user)
    return client


@pytest.fixture
def teacher_client(teacher_user):
    client = APIClient()
    client.force_authenticate(user=teacher_user)
    return client


@pytest.fixture
def student_with_contact(school, django_user_model):
    """Enqueue only snapshots drafts — a bare student is enough here."""
    student = django_user_model.objects.create_user(
        email='sendrun_student@sendrun.test',
        password='testpass123',
        user_type='student',
        school=school,
        is_approved=True,
    )
    return student, None


def _draft(student, school, month=6):
    return PreBillingInvoice.objects.create(
        student=student,
        school=school,
        status='draft',
        amount=Decimal('100.00'),
        period_start=date(2026, month, 1),
        period_end=date(2026, month, 28),
    )


def _send_all(client, month=6, year=2026):
    return client.post(
        reverse('management_pre_billing_send_all'),
        {'month': month, 'year': year},
        format='json',
    )


class TestEnqueue:
    def test_missing_period_is_400(self, management_client):
        response = management_client.post(
            reverse('management_pre_billing_send_all'), {}, format='json'
        )
        assert response.status_code == 400

    def test_no_drafts_is_400(self, management_client):
        assert _send_all(management_client).status_code == 400

    def test_second_send_all_while_live_is_409_with_run_id(
        self, management_client, school, student_with_contact
    ):
        student, _ = student_with_contact
        _draft(student, school)
        first = _send_all(management_client)
        assert first.status_code == 202

        second = _send_all(management_client)
        assert second.status_code == 409
        assert second.data['run_id'] == first.data['id']

    def test_snapshot_cutoff_excludes_later_drafts(
        self, management_client, school, student_with_contact, teacher_user
    ):
        student, _ = student_with_contact
        _draft(student, school)
        response = _send_all(management_client)
        assert response.status_code == 202

        # Draft created AFTER the run exists (other student, same period)
        from django.contrib.auth import get_user_model
        late_student = get_user_model().objects.create_user(
            email='late.draft@sendrun.test', password='pass',
            user_type='student', school=school, is_approved=True,
        )
        late = _draft(late_student, school)

        run = InvoiceSendRun.objects.get(pk=response.data['id'])
        assert run.item_count == 1
        assert late.send_items.count() == 0


class TestDetailLatestCancel:
    def test_detail_and_latest_round_trip(
        self, management_client, school, student_with_contact
    ):
        student, _ = student_with_contact
        _draft(student, school)
        run_id = _send_all(management_client).data['id']

        detail = management_client.get(
            reverse('management_send_run_detail', args=[run_id])
        )
        assert detail.status_code == 200
        assert detail.data['status'] == 'queued'
        assert detail.data['item_count'] == 1

        latest = management_client.get(
            reverse('management_send_run_latest'), {'month': 6, 'year': 2026}
        )
        assert latest.status_code == 200
        assert latest.data['run']['id'] == run_id

    def test_latest_with_no_runs_is_null(self, management_client):
        response = management_client.get(
            reverse('management_send_run_latest'), {'month': 6, 'year': 2026}
        )
        assert response.status_code == 200
        assert response.data['run'] is None

    def test_cancel_skips_pending_and_allows_new_run(
        self, management_client, school, student_with_contact
    ):
        student, _ = student_with_contact
        _draft(student, school)
        run_id = _send_all(management_client).data['id']

        cancel = management_client.post(
            reverse('management_send_run_cancel', args=[run_id])
        )
        assert cancel.status_code == 200
        assert cancel.data['status'] == 'cancelled'
        run = InvoiceSendRun.objects.get(pk=run_id)
        assert run.items.filter(status='skipped').count() == 1
        assert run.finished_at is not None

        # Period is free again — cancel released the one-live-run constraint
        assert _send_all(management_client).status_code == 202

    def test_cancel_finished_run_is_400(
        self, management_client, school, student_with_contact
    ):
        student, _ = student_with_contact
        _draft(student, school)
        run_id = _send_all(management_client).data['id']
        InvoiceSendRun.objects.filter(pk=run_id).update(
            status='done', finished_at=timezone.now()
        )
        response = management_client.post(
            reverse('management_send_run_cancel', args=[run_id])
        )
        assert response.status_code == 400


class TestRoleAndSchoolBoundaries:
    def test_teacher_cannot_enqueue_or_read(self, teacher_client):
        assert _send_all(teacher_client).status_code in (302, 403)
        response = teacher_client.get(
            reverse('management_send_run_latest'), {'month': 6, 'year': 2026}
        )
        assert response.status_code in (302, 403)

    def test_other_school_run_is_404(
        self, management_client, school, second_school, student_with_contact
    ):
        student, _ = student_with_contact
        _draft(student, school)
        run_id = _send_all(management_client).data['id']

        InvoiceSendRun.objects.filter(pk=run_id).update(school=second_school)

        detail = management_client.get(
            reverse('management_send_run_detail', args=[run_id])
        )
        assert detail.status_code == 404
        cancel = management_client.post(
            reverse('management_send_run_cancel', args=[run_id])
        )
        assert cancel.status_code == 404
