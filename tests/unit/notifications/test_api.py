"""Endpoint tests: list, mark-read, mark-all-read, preferences."""

import pytest
from django.urls import reverse
from rest_framework import status

from notifications.models import Notification, NotificationPreference


def make_notification(user, **kwargs):
    defaults = dict(
        message='Test notification',
        type='general',
        link_url='/invoice',
    )
    defaults.update(kwargs)
    return Notification.objects.create(user=user, school=user.school, **defaults)


@pytest.mark.django_db
class TestNotificationList:
    def test_returns_own_notifications_and_unread_count(
        self, teacher_client, teacher_user
    ):
        make_notification(teacher_user, message='first')
        make_notification(teacher_user, message='second', read_status=True)
        response = teacher_client.get(reverse('notification_list'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['unread_count'] == 1
        assert len(response.data['notifications']) == 2
        # newest first
        assert response.data['notifications'][0]['message'] == 'second'

    def test_does_not_leak_other_users_notifications(
        self, teacher_client, teacher_user, second_teacher
    ):
        make_notification(second_teacher, message='not yours')
        response = teacher_client.get(reverse('notification_list'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['notifications'] == []
        assert response.data['unread_count'] == 0

    def test_management_can_list_own(self, management_client, management_user):
        make_notification(management_user)
        response = management_client.get(reverse('notification_list'))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['notifications']) == 1

    def test_student_forbidden(self, student_client):
        response = student_client.get(reverse('notification_list'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_rejected(self, api_client):
        response = api_client.get(reverse('notification_list'))
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


@pytest.mark.django_db
class TestMarkRead:
    def test_marks_own_notification_read(self, teacher_client, teacher_user):
        notification = make_notification(teacher_user)
        response = teacher_client.post(
            reverse('notification_mark_read', kwargs={'notification_id': notification.id})
        )
        assert response.status_code == status.HTTP_200_OK
        notification.refresh_from_db()
        assert notification.read_status is True

    def test_cannot_mark_other_users_notification(
        self, teacher_client, second_teacher
    ):
        notification = make_notification(second_teacher)
        response = teacher_client.post(
            reverse('notification_mark_read', kwargs={'notification_id': notification.id})
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        notification.refresh_from_db()
        assert notification.read_status is False

    def test_mark_all_read(self, teacher_client, teacher_user, second_teacher):
        make_notification(teacher_user)
        make_notification(teacher_user)
        other = make_notification(second_teacher)
        response = teacher_client.post(reverse('notification_mark_all_read'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['marked_read'] == 2
        assert not Notification.objects.filter(
            user=teacher_user, read_status=False
        ).exists()
        other.refresh_from_db()
        assert other.read_status is False


@pytest.mark.django_db
class TestPreferences:
    def test_get_creates_defaults(self, teacher_client, teacher_user):
        response = teacher_client.get(reverse('notification_preferences'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['email_enabled'] is False
        assert response.data['sms_enabled'] is False
        assert NotificationPreference.objects.filter(user=teacher_user).exists()

    def test_put_updates_and_persists(self, teacher_client, teacher_user):
        response = teacher_client.put(
            reverse('notification_preferences'),
            {'email_enabled': True},
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['email_enabled'] is True
        prefs = NotificationPreference.objects.get(user=teacher_user)
        assert prefs.email_enabled is True
        assert prefs.sms_enabled is False

    def test_student_forbidden(self, student_client):
        response = student_client.get(reverse('notification_preferences'))
        assert response.status_code == status.HTTP_403_FORBIDDEN
