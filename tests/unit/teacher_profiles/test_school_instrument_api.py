"""Endpoint tests for the school-wide instrument list (dropdown source)."""

import pytest
from django.urls import reverse
from rest_framework import status

from teacher_profiles.models import SchoolInstrument


def list_url():
    return reverse('school_instrument_list')


def detail_url(instrument_id):
    return reverse('school_instrument_detail', kwargs={'instrument_id': instrument_id})


@pytest.fixture
def piano(school, db):
    return SchoolInstrument.objects.create(school=school, name='Piano')


@pytest.fixture
def other_school_instrument(second_school, db):
    return SchoolInstrument.objects.create(school=second_school, name='Theremin')


@pytest.mark.django_db
class TestSchoolInstrumentList:
    def test_teacher_can_read_list(self, teacher_client, piano):
        response = teacher_client.get(list_url())
        assert response.status_code == status.HTTP_200_OK
        assert [row['name'] for row in response.data] == ['Piano']

    def test_management_can_read_list(self, management_client, piano):
        response = management_client.get(list_url())
        assert response.status_code == status.HTTP_200_OK

    def test_list_is_school_scoped(self, teacher_client, piano, other_school_instrument):
        response = teacher_client.get(list_url())
        names = [row['name'] for row in response.data]
        assert 'Theremin' not in names

    def test_anonymous_rejected(self, api_client):
        response = api_client.get(list_url())
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


@pytest.mark.django_db
class TestSchoolInstrumentCreate:
    def test_management_creates(self, management_client, management_user):
        response = management_client.post(list_url(), {'name': 'Cello'}, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert SchoolInstrument.objects.filter(
            school=management_user.school, name='Cello'
        ).exists()

    def test_teacher_cannot_create(self, teacher_client):
        response = teacher_client.post(list_url(), {'name': 'Cello'}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_duplicate_name_rejected_case_insensitive(self, management_client, piano):
        response = management_client.post(list_url(), {'name': 'piano'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_blank_name_rejected(self, management_client):
        response = management_client.post(list_url(), {'name': '   '}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestSchoolInstrumentDetail:
    def test_management_renames(self, management_client, piano):
        response = management_client.put(
            detail_url(piano.id), {'name': 'Grand Piano'}, format='json'
        )
        assert response.status_code == status.HTTP_200_OK
        piano.refresh_from_db()
        assert piano.name == 'Grand Piano'

    def test_management_deletes(self, management_client, piano):
        response = management_client.delete(detail_url(piano.id))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not SchoolInstrument.objects.filter(pk=piano.id).exists()

    def test_teacher_cannot_delete(self, teacher_client, piano):
        response = teacher_client.delete(detail_url(piano.id))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cannot_touch_other_school_instrument(
        self, management_client, other_school_instrument
    ):
        response = management_client.delete(detail_url(other_school_instrument.id))
        assert response.status_code == status.HTTP_404_NOT_FOUND
