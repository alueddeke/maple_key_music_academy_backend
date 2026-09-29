"""
MAP-222: management reads and updates the invoice Reply-To address through the
school settings endpoint; other roles cannot.
"""
import pytest
from django.urls import reverse
from rest_framework import status

from billing.models import SchoolSettings

URL = reverse('school_settings')


@pytest.mark.django_db
def test_management_reads_invoice_reply_to(api_client, management_user, school_settings):
    school_settings.invoice_reply_to_email = 'office@example.org'
    school_settings.save()
    api_client.force_authenticate(management_user)

    response = api_client.get(URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.data['invoice_reply_to_email'] == 'office@example.org'


@pytest.mark.django_db
def test_management_updates_invoice_reply_to(api_client, management_user, school_settings):
    api_client.force_authenticate(management_user)

    response = api_client.patch(URL, {'invoice_reply_to_email': 'office@example.org'}, format='json')

    assert response.status_code == status.HTTP_200_OK
    school_settings.refresh_from_db()
    assert school_settings.invoice_reply_to_email == 'office@example.org'
    assert school_settings.updated_by == management_user


@pytest.mark.django_db
def test_management_can_clear_invoice_reply_to(api_client, management_user, school_settings):
    school_settings.invoice_reply_to_email = 'office@example.org'
    school_settings.save()
    api_client.force_authenticate(management_user)

    response = api_client.patch(URL, {'invoice_reply_to_email': ''}, format='json')

    assert response.status_code == status.HTTP_200_OK
    school_settings.refresh_from_db()
    assert school_settings.invoice_reply_to_email == ''


@pytest.mark.django_db
def test_invalid_invoice_reply_to_is_rejected(api_client, management_user, school_settings):
    api_client.force_authenticate(management_user)

    response = api_client.patch(URL, {'invoice_reply_to_email': 'not-an-email'}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'invoice_reply_to_email' in response.data
    school_settings.refresh_from_db()
    assert school_settings.invoice_reply_to_email == ''


@pytest.mark.django_db
@pytest.mark.parametrize('user_fixture', ['teacher_user', 'student_user'])
def test_non_management_cannot_update_invoice_reply_to(api_client, school_settings, user_fixture, request):
    api_client.force_authenticate(request.getfixturevalue(user_fixture))

    response = api_client.patch(URL, {'invoice_reply_to_email': 'office@example.org'}, format='json')

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert SchoolSettings.objects.get(pk=school_settings.pk).invoice_reply_to_email == ''
