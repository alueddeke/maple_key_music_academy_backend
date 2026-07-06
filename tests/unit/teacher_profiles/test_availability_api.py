"""Endpoint + validation tests for teacher availability CRUD."""

import pytest
from django.urls import reverse
from rest_framework import status

from teacher_profiles.models import TeacherAvailability, TeacherProfile


def availability_list_url(teacher_id):
    return reverse('teacher_availability_list', kwargs={'teacher_id': teacher_id})


def availability_url(teacher_id, slot_id):
    return reverse(
        'teacher_availability_detail',
        kwargs={'teacher_id': teacher_id, 'slot_id': slot_id},
    )


VALID_SLOT = {'day_of_week': 0, 'start_time': '09:00', 'end_time': '12:00'}


@pytest.fixture
def teacher_profile(teacher_user, db):
    return TeacherProfile.objects.create(teacher=teacher_user, school=teacher_user.school)


@pytest.fixture
def monday_morning(teacher_profile, db):
    return TeacherAvailability.objects.create(
        profile=teacher_profile,
        day_of_week=0,
        start_time='09:00',
        end_time='12:00',
    )


@pytest.mark.django_db
class TestAvailabilityCreate:
    def test_teacher_adds_slot_to_own_profile(self, teacher_client, teacher_user):
        response = teacher_client.post(
            availability_list_url(teacher_user.id), VALID_SLOT, format='json'
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['day_of_week'] == 0
        assert response.data['day_of_week_display'] == 'Monday'
        assert response.data['start_time'] == '09:00:00'
        assert response.data['end_time'] == '12:00:00'

    def test_management_adds_slot_to_any_teacher(self, management_client, teacher_user):
        response = management_client.post(
            availability_list_url(teacher_user.id), VALID_SLOT, format='json'
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_teacher_cannot_add_to_other_teacher(self, teacher_client, second_teacher):
        response = teacher_client.post(
            availability_list_url(second_teacher.id), VALID_SLOT, format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_student_forbidden(self, student_client, teacher_user):
        response = student_client.post(
            availability_list_url(teacher_user.id), VALID_SLOT, format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_end_before_start_rejected(self, teacher_client, teacher_user):
        payload = {'day_of_week': 1, 'start_time': '14:00', 'end_time': '13:00'}
        response = teacher_client.post(
            availability_list_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_end_equal_start_rejected(self, teacher_client, teacher_user):
        payload = {'day_of_week': 1, 'start_time': '14:00', 'end_time': '14:00'}
        response = teacher_client.post(
            availability_list_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_day_rejected(self, teacher_client, teacher_user):
        payload = dict(VALID_SLOT, day_of_week=7)
        response = teacher_client.post(
            availability_list_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_overlapping_slot_same_day_rejected(
        self, teacher_client, teacher_user, monday_morning
    ):
        payload = {'day_of_week': 0, 'start_time': '11:00', 'end_time': '13:00'}
        response = teacher_client.post(
            availability_list_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_adjacent_slot_same_day_allowed(
        self, teacher_client, teacher_user, monday_morning
    ):
        payload = {'day_of_week': 0, 'start_time': '12:00', 'end_time': '15:00'}
        response = teacher_client.post(
            availability_list_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_same_window_different_day_allowed(
        self, teacher_client, teacher_user, monday_morning
    ):
        payload = {'day_of_week': 2, 'start_time': '09:00', 'end_time': '12:00'}
        response = teacher_client.post(
            availability_list_url(teacher_user.id), payload, format='json'
        )
        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestAvailabilityUpdateDelete:
    def test_teacher_updates_own_slot(self, teacher_client, teacher_user, monday_morning):
        response = teacher_client.put(
            availability_url(teacher_user.id, monday_morning.id),
            {'end_time': '13:00'},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        monday_morning.refresh_from_db()
        assert str(monday_morning.end_time) == '13:00:00'

    def test_update_does_not_conflict_with_self(
        self, teacher_client, teacher_user, monday_morning
    ):
        """Updating a slot must exclude itself from the overlap check."""
        response = teacher_client.put(
            availability_url(teacher_user.id, monday_morning.id),
            {'start_time': '10:00', 'end_time': '12:00'},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK

    def test_teacher_deletes_own_slot(self, teacher_client, teacher_user, monday_morning):
        response = teacher_client.delete(
            availability_url(teacher_user.id, monday_morning.id)
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not TeacherAvailability.objects.filter(pk=monday_morning.id).exists()

    def test_teacher_cannot_delete_other_teacher_slot(
        self, api_client, second_teacher, teacher_user, monday_morning
    ):
        api_client.force_authenticate(user=second_teacher)
        response = api_client.delete(
            availability_url(teacher_user.id, monday_morning.id)
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert TeacherAvailability.objects.filter(pk=monday_morning.id).exists()

    def test_slot_scoped_to_profile(self, management_client, second_teacher, monday_morning):
        response = management_client.delete(
            availability_url(second_teacher.id, monday_morning.id)
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestAvailabilityList:
    def test_list_sorted_by_day_then_time(
        self, teacher_client, teacher_user, teacher_profile
    ):
        TeacherAvailability.objects.create(
            profile=teacher_profile, day_of_week=4, start_time='09:00', end_time='10:00'
        )
        TeacherAvailability.objects.create(
            profile=teacher_profile, day_of_week=0, start_time='15:00', end_time='17:00'
        )
        TeacherAvailability.objects.create(
            profile=teacher_profile, day_of_week=0, start_time='08:00', end_time='09:00'
        )
        response = teacher_client.get(availability_list_url(teacher_user.id))
        assert response.status_code == status.HTTP_200_OK
        slots = [(s['day_of_week'], s['start_time']) for s in response.data]
        assert slots == [(0, '08:00:00'), (0, '15:00:00'), (4, '09:00:00')]

    def test_profile_endpoint_nests_availability(
        self, teacher_client, teacher_user, monday_morning
    ):
        response = teacher_client.get(
            reverse('teacher_profile_detail', kwargs={'teacher_id': teacher_user.id})
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['availability']) == 1
        assert response.data['availability'][0]['day_of_week_display'] == 'Monday'
