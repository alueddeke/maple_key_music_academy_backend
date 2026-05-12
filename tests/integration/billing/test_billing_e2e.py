"""
End-to-end integration test for the batch billing workflow.

Happy path: teacher creates batch -> adds two lesson items (one trial, one completed) ->
submits -> management approves -> Lesson (trial path) + StudentInvoice (completed path)
records exist with correct values, and the teacher downloads a paystub PDF artifact
generated on-demand from the approved batch.

The first lesson item is sent with status='completed' but auto-promoted to 'trial' by
BatchLessonItem.save() because the student has no prior Lesson or BatchLessonItem records.
The second item remains 'completed'. On approval, management_approve_batch creates one
Lesson for the trial item and one StudentInvoice for the completed item, and returns a
CSV HttpResponse (not JSON). TeacherPaystub is NOT a DB model — it is generated on-demand
by download_paystub and returned as application/pdf.
"""

import pytest
from decimal import Decimal
from datetime import date, time
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model

from billing.models import (
    MonthlyInvoiceBatch,
    BatchLessonItem,
    Lesson,
    StudentInvoice,
    BillableContact,
)

User = get_user_model()


@pytest.fixture
def management_client(management_user):
    """Separate APIClient instance authenticated as management_user.

    Uses a dedicated APIClient (not the shared api_client fixture) so that
    teacher_client and management_client don't share state — both are used
    in the same test method and force_authenticate on a shared client would
    cause the last call to win.
    """
    client = APIClient()
    client.force_authenticate(user=management_user)
    return client


@pytest.fixture
def teacher_client(teacher_user):
    """Separate APIClient instance authenticated as teacher_user."""
    client = APIClient()
    client.force_authenticate(user=teacher_user)
    return client


@pytest.fixture
def student(school, db):
    """Brand-new student with a BillableContact — no prior lessons so first item auto-promotes to 'trial'."""
    s = User.objects.create_user(
        email="student@e2etest.com",
        password="pass",
        user_type="student",
        first_name="E2E",
        last_name="Student",
        school=school,
        is_approved=True,
    )
    BillableContact.objects.create(
        student=s,
        school=school,
        contact_type='parent',
        first_name='E2E',
        last_name='Parent',
        email='parent@e2etest.com',
        phone='416-555-0001',
        street_address='1 E2E St',
        city='Toronto',
        province='ON',
        postal_code='M1A 1A1',
        is_primary=True,
    )
    return s


@pytest.mark.django_db
class TestBatchSubmitApprovePaystubCreated:
    def test_batch_submit_approve_paystub_created(
        self, teacher_client, management_client, teacher_user, management_user,
        student, school, school_settings
    ):
        # Step 1: Teacher creates batch
        url = reverse('teacher_monthly_batches')
        response = teacher_client.post(url, {'month': 4, 'year': 2026}, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        batch_id = response.data['id']

        # Step 2: Add first lesson item — status='completed' in request but auto-promoted
        # to 'trial' by BatchLessonItem.save() because student has zero prior Lesson or
        # BatchLessonItem records.
        url = reverse('batch_add_lesson', kwargs={'batch_id': batch_id})
        response = teacher_client.post(url, {
            'student': student.id,
            'scheduled_date': '2026-04-08',
            'start_time': '15:00:00',
            'duration': '1.0',
            'lesson_type': 'in_person',
            'status': 'completed',
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        # Confirm auto-promotion to 'trial' occurred
        first_item = BatchLessonItem.objects.get(id=response.data['id'])
        assert first_item.status == 'trial'

        # Step 3: Add second lesson item — one prior BatchLessonItem now exists for this
        # student so the auto-trial override will NOT fire; item stays 'completed'.
        response = teacher_client.post(url, {
            'student': student.id,
            'scheduled_date': '2026-04-15',
            'start_time': '15:00:00',
            'duration': '1.0',
            'lesson_type': 'in_person',
            'status': 'completed',
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        second_item = BatchLessonItem.objects.get(id=response.data['id'])
        assert second_item.status == 'completed'

        # Step 4: Teacher submits batch
        url = reverse('batch_submit', kwargs={'batch_id': batch_id})
        response = teacher_client.post(url, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Step 5: Management approves — returns CSV HttpResponse (not JSON)
        url = reverse('management_approve_batch', kwargs={'batch_id': batch_id})
        response = management_client.post(url, format='json')
        assert response.status_code == 200
        assert 'text/csv' in response.get('Content-Type', '')

        # Step 6: Assert records created after approval
        # trial item -> Lesson record created (is_trial=True)
        assert Lesson.objects.filter(school=school).count() == 1
        lesson = Lesson.objects.get(school=school)
        assert lesson.is_trial is True
        assert lesson.status == 'trial'
        # Rate locked from school settings at lesson creation; use teacher_user.hourly_rate
        # to stay valid if conftest changes the rate.
        assert lesson.teacher_rate == teacher_user.hourly_rate

        # completed item -> StudentInvoice record created
        assert StudentInvoice.objects.filter(school=school).count() == 1
        student_invoice = StudentInvoice.objects.get(school=school)
        assert student_invoice.batch_id == batch_id
        assert student_invoice.student_id == student.id
        assert student_invoice.amount > 0

        # Batch state after approval
        batch = MonthlyInvoiceBatch.objects.get(id=batch_id)
        assert batch.status == 'approved'
        assert batch.reviewed_by_id == management_user.id

        # Step 7: Teacher downloads paystub PDF — generated on-demand by download_paystub
        # endpoint (TeacherPaystub is not a DB model).
        url = reverse('download_paystub', kwargs={'batch_id': batch_id})
        response = teacher_client.get(url)
        assert response.status_code == 200
        assert response.get('Content-Type') == 'application/pdf'
        assert len(response.content) > 0
