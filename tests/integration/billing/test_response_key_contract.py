"""
MAP-260: response keys the strict frontend schemas rely on.

- A name derived from a nullable FK is always present, as null when the FK is empty.
- School settings no longer expose the deprecated invoice_recipient_email.
- Deleting an approved email returns an empty 204.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from billing.models import (
    ApprovedEmail,
    Invoice,
    InvoiceRecipientEmail,
    SchoolSettings,
    UserRegistrationRequest,
)

INVOICE_NAME_KEYS = ('created_by_name', 'approved_by_name')
DETAILED_INVOICE_NAME_KEYS = (
    'created_by_name', 'approved_by_name', 'rejected_by_name', 'last_edited_by_name',
)


def _teacher_invoice(teacher, **kwargs):
    return Invoice.objects.create(
        invoice_type='teacher_payment',
        teacher=teacher,
        school=teacher.school,
        status='pending',
        payment_balance=Decimal('0.00'),
        **kwargs,
    )


def _by_id(rows, pk):
    return next(row for row in rows if row['id'] == pk)


@pytest.mark.django_db
def test_invoice_null_fks_emit_null_name_keys(api_client, management_user, teacher_user):
    empty = _teacher_invoice(teacher_user)
    filled = _teacher_invoice(
        teacher_user, created_by=management_user, approved_by=management_user,
    )
    api_client.force_authenticate(management_user)

    response = api_client.get(reverse('management_teacher_detail', args=[teacher_user.id]))

    assert response.status_code == status.HTTP_200_OK
    rows = response.data['recent_invoices']
    empty_row, filled_row = _by_id(rows, empty.id), _by_id(rows, filled.id)
    for key in INVOICE_NAME_KEYS:
        assert empty_row[key] is None
        assert filled_row[key] == management_user.get_full_name()
    # A teacher-payment invoice has no student: the key is present, as null.
    assert empty_row['student_name'] is None
    assert empty_row['teacher_name'] == teacher_user.get_full_name()


@pytest.mark.django_db
def test_detailed_invoice_null_fks_emit_null_name_keys(api_client, management_user, teacher_user):
    empty = _teacher_invoice(teacher_user)
    filled = _teacher_invoice(
        teacher_user,
        created_by=management_user,
        approved_by=management_user,
        rejected_by=management_user,
        last_edited_by=management_user,
    )
    api_client.force_authenticate(teacher_user)

    response = api_client.get(reverse('teacher_invoice_list'))

    assert response.status_code == status.HTTP_200_OK
    empty_row, filled_row = _by_id(response.data, empty.id), _by_id(response.data, filled.id)
    for key in DETAILED_INVOICE_NAME_KEYS:
        assert empty_row[key] is None
        assert filled_row[key] == management_user.get_full_name()
    assert empty_row['student_name'] is None
    assert empty_row['teacher_name'] == teacher_user.get_full_name()


@pytest.mark.django_db
def test_unreviewed_registration_request_has_null_reviewed_by_name(
    api_client, management_user, school,
):
    pending = UserRegistrationRequest.objects.create(
        email='pending@example.org', user_type='teacher', school=school,
    )
    reviewed = UserRegistrationRequest.objects.create(
        email='reviewed@example.org', user_type='teacher', school=school,
        status='approved', reviewed_by=management_user,
    )
    api_client.force_authenticate(management_user)

    response = api_client.get(reverse('registration_request_list'))

    assert response.status_code == status.HTTP_200_OK
    assert _by_id(response.data, pending.id)['reviewed_by_name'] is None
    assert _by_id(response.data, reviewed.id)['reviewed_by_name'] == management_user.get_full_name()


@pytest.mark.django_db
def test_invoice_recipient_without_creator_has_null_created_by_name(
    api_client, management_user, school,
):
    orphan = InvoiceRecipientEmail.objects.create(school=school, email='orphan@example.org')
    owned = InvoiceRecipientEmail.objects.create(
        school=school, email='owned@example.org', created_by=management_user,
    )
    api_client.force_authenticate(management_user)

    response = api_client.get(reverse('list_invoice_recipients'))

    assert response.status_code == status.HTTP_200_OK
    assert _by_id(response.data, orphan.id)['created_by_name'] is None
    assert _by_id(response.data, owned.id)['created_by_name'] == management_user.get_full_name()


@pytest.mark.django_db
def test_school_settings_never_updated_has_null_updated_by_name(
    api_client, management_user, school_settings,
):
    SchoolSettings.objects.filter(pk=school_settings.pk).update(updated_by=None)
    api_client.force_authenticate(management_user)

    response = api_client.get(reverse('school_settings'))

    assert response.status_code == status.HTTP_200_OK
    assert response.data['updated_by_name'] is None


@pytest.mark.django_db
def test_school_settings_omit_invoice_recipient_email(api_client, management_user, school_settings):
    api_client.force_authenticate(management_user)
    url = reverse('school_settings')

    get_response = api_client.get(url)
    patch_response = api_client.patch(
        url, {'invoice_reply_to_email': 'office@example.org'}, format='json',
    )

    assert get_response.status_code == status.HTTP_200_OK
    assert 'invoice_recipient_email' not in get_response.data
    assert patch_response.status_code == status.HTTP_200_OK
    assert 'invoice_recipient_email' not in patch_response.data


@pytest.mark.django_db
def test_approved_email_delete_returns_empty_204(api_client, management_user):
    approved = ApprovedEmail.objects.create(
        email='invitee@example.org', user_type='teacher', approved_by=management_user,
    )
    api_client.force_authenticate(management_user)

    response = api_client.delete(reverse('approved_email_delete', args=[approved.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    # The test client strips 204 bodies, so assert on what the view returned.
    assert response.data is None
    assert not ApprovedEmail.objects.filter(pk=approved.pk).exists()
