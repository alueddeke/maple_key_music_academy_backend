"""Endpoint + permission tests for the teacher profile detail endpoint."""

import pytest
from django.urls import reverse
from rest_framework import status

from teacher_profiles.models import TeacherProfile


def profile_url(teacher_id):
    return reverse('teacher_profile_detail', kwargs={'teacher_id': teacher_id})


@pytest.mark.django_db
class TestTeacherProfileGet:
    def test_teacher_gets_own_profile_auto_created(self, teacher_client, teacher_user):
        response = teacher_client.get(profile_url(teacher_user.id))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['teacher'] == teacher_user.id
        assert response.data['instruments'] == []
        assert response.data['availability'] == []
        assert TeacherProfile.objects.filter(teacher=teacher_user).exists()

    def test_management_gets_any_teacher_in_school(
        self, management_client, teacher_user
    ):
        response = management_client.get(profile_url(teacher_user.id))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['teacher'] == teacher_user.id

    def test_teacher_cannot_get_other_teacher_profile(
        self, teacher_client, second_teacher
    ):
        response = teacher_client.get(profile_url(second_teacher.id))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_management_cannot_get_other_school_teacher(
        self, management_client, other_school_teacher
    ):
        response = management_client.get(profile_url(other_school_teacher.id))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_student_forbidden(self, student_client, teacher_user):
        response = student_client.get(profile_url(teacher_user.id))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_rejected(self, api_client, teacher_user):
        response = api_client.get(profile_url(teacher_user.id))
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_nonexistent_teacher_404(self, management_client):
        response = management_client.get(profile_url(999999))
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestTeacherProfileUpdate:
    def test_teacher_updates_own_profile_fields(self, teacher_client, teacher_user):
        payload = {
            'notes': 'Prefers teaching mornings.',
            'teachable_area': 'Downtown Toronto, North York',
            'lat': '43.653226',
            'lng': '-79.383184',
        }
        response = teacher_client.put(
            profile_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_200_OK

        profile = TeacherProfile.objects.get(teacher=teacher_user)
        assert profile.notes == 'Prefers teaching mornings.'
        assert profile.teachable_area == 'Downtown Toronto, North York'
        assert str(profile.lat) == '43.653226'
        assert str(profile.lng) == '-79.383184'

    def test_management_updates_any_teacher_profile(
        self, management_client, teacher_user
    ):
        response = management_client.put(
            profile_url(teacher_user.id), {'notes': 'Set by management'}, format='json'
        )
        assert response.status_code == status.HTTP_200_OK
        assert TeacherProfile.objects.get(teacher=teacher_user).notes == 'Set by management'

    def test_teacher_cannot_update_other_teacher(self, teacher_client, second_teacher):
        response = teacher_client.put(
            profile_url(second_teacher.id), {'notes': 'nope'}, format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not TeacherProfile.objects.filter(
            teacher=second_teacher, notes='nope'
        ).exists()

    def test_invalid_latitude_rejected(self, teacher_client, teacher_user):
        response = teacher_client.put(
            profile_url(teacher_user.id), {'lat': '95.0'}, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_teacher_field_not_writable(self, teacher_client, teacher_user, second_teacher):
        """The profile's teacher FK cannot be reassigned via the API."""
        response = teacher_client.put(
            profile_url(teacher_user.id), {'teacher': second_teacher.id}, format='json'
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['teacher'] == teacher_user.id

    def test_round_trip_get_after_put(self, teacher_client, teacher_user):
        teacher_client.put(
            profile_url(teacher_user.id), {'notes': 'persisted'}, format='json'
        )
        response = teacher_client.get(profile_url(teacher_user.id))
        assert response.data['notes'] == 'persisted'
