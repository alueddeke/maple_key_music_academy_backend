"""Endpoint + validation tests for teacher instrument CRUD."""

import pytest
from django.urls import reverse
from rest_framework import status

from teacher_profiles.models import TeacherInstrument, TeacherProfile


def instruments_url(teacher_id):
    return reverse('teacher_instrument_list', kwargs={'teacher_id': teacher_id})


def instrument_url(teacher_id, instrument_id):
    return reverse(
        'teacher_instrument_detail',
        kwargs={'teacher_id': teacher_id, 'instrument_id': instrument_id},
    )


VALID_PAYLOAD = {
    'instrument': 'Piano',
    'skill_ceiling': 'advanced',
    'rate': '65.00',
    'teaches_theory': True,
    'teaches_history': False,
    'teaches_rcm_prep': True,
}


@pytest.fixture
def teacher_profile(teacher_user, db):
    return TeacherProfile.objects.create(teacher=teacher_user, school=teacher_user.school)


@pytest.fixture
def piano(teacher_profile, db):
    return TeacherInstrument.objects.create(
        profile=teacher_profile,
        instrument='Piano',
        skill_ceiling='intermediate',
    )


@pytest.mark.django_db
class TestInstrumentCreate:
    def test_teacher_adds_instrument_to_own_profile(self, teacher_client, teacher_user):
        response = teacher_client.post(
            instruments_url(teacher_user.id), VALID_PAYLOAD, format='json'
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['instrument'] == 'Piano'
        assert response.data['skill_ceiling'] == 'advanced'
        assert response.data['rate'] == '65.00'
        assert response.data['teaches_theory'] is True
        assert response.data['teaches_rcm_prep'] is True

    def test_management_adds_instrument_to_any_teacher(
        self, management_client, teacher_user
    ):
        response = management_client.post(
            instruments_url(teacher_user.id), VALID_PAYLOAD, format='json'
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_teacher_cannot_add_to_other_teacher(self, teacher_client, second_teacher):
        response = teacher_client.post(
            instruments_url(second_teacher.id), VALID_PAYLOAD, format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_student_forbidden(self, student_client, teacher_user):
        response = student_client.post(
            instruments_url(teacher_user.id), VALID_PAYLOAD, format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_rate_optional(self, teacher_client, teacher_user):
        payload = {'instrument': 'Guitar', 'skill_ceiling': 'beginner'}
        response = teacher_client.post(
            instruments_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['rate'] is None

    def test_negative_rate_rejected(self, teacher_client, teacher_user):
        payload = dict(VALID_PAYLOAD, rate='-5.00')
        response = teacher_client.post(
            instruments_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_skill_ceiling_rejected(self, teacher_client, teacher_user):
        payload = dict(VALID_PAYLOAD, skill_ceiling='virtuoso')
        response = teacher_client.post(
            instruments_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_blank_instrument_rejected(self, teacher_client, teacher_user):
        payload = dict(VALID_PAYLOAD, instrument='   ')
        response = teacher_client.post(
            instruments_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_duplicate_instrument_rejected_case_insensitive(
        self, teacher_client, teacher_user, piano
    ):
        payload = dict(VALID_PAYLOAD, instrument='piano')
        response = teacher_client.post(
            instruments_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestInstrumentUpdateDelete:
    def test_teacher_updates_own_instrument(self, teacher_client, teacher_user, piano):
        response = teacher_client.put(
            instrument_url(teacher_user.id, piano.id),
            {'skill_ceiling': 'advanced', 'rate': '80.00'},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        piano.refresh_from_db()
        assert piano.skill_ceiling == 'advanced'
        assert str(piano.rate) == '80.00'

    def test_management_updates_any_instrument(
        self, management_client, teacher_user, piano
    ):
        response = management_client.put(
            instrument_url(teacher_user.id, piano.id),
            {'teaches_history': True},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        piano.refresh_from_db()
        assert piano.teaches_history is True

    def test_teacher_cannot_update_other_teacher_instrument(
        self, api_client, second_teacher, teacher_user, piano
    ):
        api_client.force_authenticate(user=second_teacher)
        response = api_client.put(
            instrument_url(teacher_user.id, piano.id),
            {'skill_ceiling': 'beginner'},
            format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_teacher_deletes_own_instrument(self, teacher_client, teacher_user, piano):
        response = teacher_client.delete(instrument_url(teacher_user.id, piano.id))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not TeacherInstrument.objects.filter(pk=piano.id).exists()

    def test_delete_nonexistent_instrument_404(self, teacher_client, teacher_user):
        response = teacher_client.delete(instrument_url(teacher_user.id, 999999))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_instrument_scoped_to_profile(
        self, management_client, second_teacher, piano
    ):
        """An instrument id belonging to teacher A is a 404 under teacher B's profile."""
        response = management_client.delete(
            instrument_url(second_teacher.id, piano.id)
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert TeacherInstrument.objects.filter(pk=piano.id).exists()


@pytest.mark.django_db
class TestInstrumentList:
    def test_list_returns_profile_instruments_sorted(
        self, teacher_client, teacher_user, teacher_profile
    ):
        TeacherInstrument.objects.create(
            profile=teacher_profile, instrument='Violin', skill_ceiling='advanced'
        )
        TeacherInstrument.objects.create(
            profile=teacher_profile, instrument='Cello', skill_ceiling='beginner'
        )
        response = teacher_client.get(instruments_url(teacher_user.id))
        assert response.status_code == status.HTTP_200_OK
        assert [i['instrument'] for i in response.data] == ['Cello', 'Violin']

    def test_profile_endpoint_nests_instruments(
        self, teacher_client, teacher_user, piano
    ):
        response = teacher_client.get(
            reverse('teacher_profile_detail', kwargs={'teacher_id': teacher_user.id})
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['instruments']) == 1
        assert response.data['instruments'][0]['instrument'] == 'Piano'
