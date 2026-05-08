"""
Integration tests for password reset endpoints in custom_auth/views.py.
Requirement: TST-03

Endpoints covered:
- POST /api/auth/password-reset/          (password_reset_request)
- POST /api/auth/password-reset/validate/ (password_reset_validate_token)
- POST /api/auth/password-reset/confirm/  (password_reset_confirm)
"""
import pytest
from django.urls import reverse
from django.core import mail
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from rest_framework import status

User = get_user_model()


@pytest.mark.django_db
class TestPasswordResetRequest:
    """Tests for POST /api/auth/password-reset/ (password_reset_request)."""

    def test_existing_user_receives_email_and_200(self, api_client, teacher_user):
        """Existing user gets success response and email is sent."""
        mail.outbox = []
        url = reverse('password_reset_request')
        response = api_client.post(url, {'email': teacher_user.email}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'message' in response.data
        assert 'If an account exists' in response.data['message']
        assert len(mail.outbox) == 1
        assert 'Password Reset' in mail.outbox[0].subject
        assert teacher_user.email in mail.outbox[0].to

    def test_nonexistent_user_returns_same_message_no_email(self, api_client, db):
        """Non-existent user gets identical message (no enumeration) and no email sent."""
        mail.outbox = []
        url = reverse('password_reset_request')
        response = api_client.post(url, {'email': 'nobody@example.com'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'message' in response.data
        assert 'If an account exists' in response.data['message']
        assert len(mail.outbox) == 0

    def test_missing_email_returns_400(self, api_client):
        """Missing email field returns 400."""
        url = reverse('password_reset_request')
        response = api_client.post(url, {}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data


@pytest.mark.django_db
class TestPasswordResetValidate:
    """Tests for POST /api/auth/password-reset/validate/ (password_reset_validate_token)."""

    def test_valid_uid_and_token_returns_200(self, api_client, teacher_user):
        """Valid uid and token returns 200 with valid=True and email."""
        uid = urlsafe_base64_encode(force_bytes(teacher_user.pk))
        token = default_token_generator.make_token(teacher_user)

        url = reverse('password_reset_validate')
        response = api_client.post(url, {'uid': uid, 'token': token}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['valid'] is True
        assert response.data['email'] == teacher_user.email

    def test_tampered_token_returns_400(self, api_client, teacher_user):
        """Tampered token with valid uid returns 400 with valid=False."""
        uid = urlsafe_base64_encode(force_bytes(teacher_user.pk))
        bad_token = 'aaa-bbb-ccc'

        url = reverse('password_reset_validate')
        response = api_client.post(url, {'uid': uid, 'token': bad_token}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['valid'] is False

    def test_invalid_uid_returns_400(self, api_client, teacher_user):
        """Invalid (non-base64) uid returns 400."""
        token = default_token_generator.make_token(teacher_user)

        url = reverse('password_reset_validate')
        response = api_client.post(url, {'uid': '!!!notbase64!!!', 'token': token}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_fields_returns_400(self, api_client):
        """Missing uid and token returns 400."""
        url = reverse('password_reset_validate')
        response = api_client.post(url, {}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestPasswordResetConfirm:
    """Tests for POST /api/auth/password-reset/confirm/ (password_reset_confirm)."""

    def test_valid_reset_changes_password(self, api_client, teacher_user):
        """Valid uid+token with matching passwords resets the password."""
        uid = urlsafe_base64_encode(force_bytes(teacher_user.pk))
        token = default_token_generator.make_token(teacher_user)

        url = reverse('password_reset_confirm')
        response = api_client.post(url, {
            'uid': uid,
            'token': token,
            'password': 'NewSecure!Pass1',
            'confirm_password': 'NewSecure!Pass1',
        }, format='json')

        assert response.status_code == status.HTTP_200_OK

        teacher_user.refresh_from_db()
        assert teacher_user.check_password('NewSecure!Pass1') is True
        assert teacher_user.check_password('testpass123') is False

    def test_password_mismatch_returns_400(self, api_client, teacher_user):
        """Mismatched passwords return 400 and old password remains valid."""
        uid = urlsafe_base64_encode(force_bytes(teacher_user.pk))
        token = default_token_generator.make_token(teacher_user)

        url = reverse('password_reset_confirm')
        response = api_client.post(url, {
            'uid': uid,
            'token': token,
            'password': 'NewSecure!Pass1',
            'confirm_password': 'DifferentPass!2',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data
        assert 'Passwords do not match' in response.data['error']

        # Old password still valid
        assert User.objects.get(pk=teacher_user.pk).check_password('testpass123') is True

    def test_invalid_token_returns_400(self, api_client, teacher_user):
        """Valid uid but invalid token returns 400."""
        uid = urlsafe_base64_encode(force_bytes(teacher_user.pk))

        url = reverse('password_reset_confirm')
        response = api_client.post(url, {
            'uid': uid,
            'token': 'invalid-token-xyz',
            'password': 'NewSecure!Pass1',
            'confirm_password': 'NewSecure!Pass1',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_weak_password_returns_400(self, api_client, teacher_user):
        """Weak password that fails validation returns 400."""
        uid = urlsafe_base64_encode(force_bytes(teacher_user.pk))
        token = default_token_generator.make_token(teacher_user)

        url = reverse('password_reset_confirm')
        response = api_client.post(url, {
            'uid': uid,
            'token': token,
            'password': '1',
            'confirm_password': '1',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Either the error message mentions validation failure, or details are non-empty
        assert (
            'Password validation failed' in response.data.get('error', '')
            or bool(response.data.get('details'))
        )
