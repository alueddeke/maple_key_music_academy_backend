"""
Integration tests for JWT auth endpoints in custom_auth/views.py.
Requirement: TST-01

Endpoints covered:
- POST /api/auth/token/         (get_jwt_token)
- POST /api/auth/token/refresh/ (refresh_jwt_token)
- POST /api/auth/logout/        (logout)
- GET  /api/auth/user/          (user_profile)
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from billing.models import UserRegistrationRequest

User = get_user_model()


@pytest.mark.django_db
class TestJWTLogin:
    """Integration tests for POST /api/auth/token/ (get_jwt_token)."""

    def test_valid_credentials_return_200_with_tokens(self, api_client, teacher_user):
        url = reverse('get_jwt_token')
        response = api_client.post(url, {
            'email': teacher_user.email,
            'password': 'testpass123',
        }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'access_token' in response.data
        assert 'refresh_token' in response.data
        assert response.data['user']['email'] == teacher_user.email
        assert response.data['user']['user_type'] == 'teacher'

    def test_invalid_password_returns_401(self, api_client, teacher_user):
        url = reverse('get_jwt_token')
        response = api_client.post(url, {
            'email': teacher_user.email,
            'password': 'wrongpassword',
        }, format='json')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert 'error' in response.data
        assert 'Invalid email or password' in response.data['error']

    def test_nonexistent_email_returns_401(self, api_client, db):
        url = reverse('get_jwt_token')
        response = api_client.post(url, {
            'email': 'nobody@nowhere.com',
            'password': 'somepassword',
        }, format='json')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unapproved_user_returns_403(self, api_client, unapproved_teacher):
        url = reverse('get_jwt_token')
        response = api_client.post(url, {
            'email': unapproved_teacher.email,
            'password': 'testpass123',
        }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert 'error' in response.data
        assert 'Account not approved' in response.data['error']

    def test_missing_email_returns_400(self, api_client):
        url = reverse('get_jwt_token')
        response = api_client.post(url, {
            'password': 'foo',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_password_returns_400(self, api_client):
        url = reverse('get_jwt_token')
        response = api_client.post(url, {
            'email': 'a@b.com',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_pending_registration_request_returns_403(self, api_client, db):
        UserRegistrationRequest.objects.create(
            email='pending@test.com',
            first_name='P',
            last_name='R',
            user_type='teacher',
            status='pending',
        )
        url = reverse('get_jwt_token')
        response = api_client.post(url, {
            'email': 'pending@test.com',
            'password': 'anypassword',
        }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert 'error' in response.data
        assert 'Approval pending' in response.data['error']

    def test_rejected_registration_request_returns_403(self, api_client, db):
        UserRegistrationRequest.objects.create(
            email='rejected@test.com',
            first_name='R',
            last_name='J',
            user_type='teacher',
            status='rejected',
        )
        url = reverse('get_jwt_token')
        response = api_client.post(url, {
            'email': 'rejected@test.com',
            'password': 'anypassword',
        }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert 'error' in response.data
        assert 'Registration rejected' in response.data['error']


@pytest.mark.django_db
class TestJWTRefresh:
    """Integration tests for POST /api/auth/token/refresh/ (refresh_jwt_token)."""

    def test_valid_refresh_returns_new_access_token(self, api_client, teacher_user):
        refresh = RefreshToken.for_user(teacher_user)
        original_access = str(refresh.access_token)
        url = reverse('refresh_jwt_token')
        response = api_client.post(url, {
            'refresh': str(refresh),
        }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'access_token' in response.data
        assert isinstance(response.data['access_token'], str)
        assert len(response.data['access_token']) > 0
        assert response.data['access_token'] != original_access  # must be a new token

    def test_missing_refresh_returns_400(self, api_client):
        url = reverse('refresh_jwt_token')
        response = api_client.post(url, {}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data
        assert 'required' in response.data['error'].lower()

    def test_invalid_refresh_returns_401(self, api_client):
        url = reverse('refresh_jwt_token')
        response = api_client.post(url, {
            'refresh': 'not-a-jwt',
        }, format='json')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert 'error' in response.data
        assert 'Invalid refresh token' in response.data['error']

    def test_blacklisted_refresh_returns_401(self, api_client, teacher_user):
        refresh = RefreshToken.for_user(teacher_user)
        refresh.blacklist()

        url = reverse('refresh_jwt_token')
        response = api_client.post(url, {
            'refresh': str(refresh),
        }, format='json')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestJWTLogout:
    """Integration tests for POST /api/auth/logout/ (logout)."""

    def test_logout_blacklists_refresh_token(self, api_client, teacher_user):
        refresh = RefreshToken.for_user(teacher_user)
        refresh_str = str(refresh)

        # Step 1: Logout with the valid refresh token
        logout_url = reverse('logout')
        logout_response = api_client.post(logout_url, {
            'refresh': refresh_str,
        }, format='json')

        assert logout_response.status_code == status.HTTP_200_OK
        assert 'message' in logout_response.data
        assert 'Successfully logged out' in logout_response.data['message']

        # Step 2: Attempt to reuse the same refresh token — must be rejected
        refresh_url = reverse('refresh_jwt_token')
        refresh_response = api_client.post(refresh_url, {
            'refresh': refresh_str,
        }, format='json')

        assert refresh_response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_logout_missing_refresh_returns_400(self, api_client):
        url = reverse('logout')
        response = api_client.post(url, {}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_logout_invalid_refresh_returns_401(self, api_client):
        url = reverse('logout')
        response = api_client.post(url, {
            'refresh': 'garbage',
        }, format='json')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestUserProfile:
    """Integration tests for GET /api/auth/user/ (user_profile)."""

    def test_authenticated_user_returns_200_with_profile(self, api_client, teacher_user):
        api_client.force_authenticate(user=teacher_user)
        url = reverse('user_profile')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['user']['email'] == teacher_user.email
        assert response.data['user']['user_type'] == 'teacher'
        assert 'first_name' in response.data['user']

    def test_unauthenticated_returns_401(self, api_client):
        url = reverse('user_profile')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_invalid_bearer_token_returns_401(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION='Bearer not-a-real-jwt')
        url = reverse('user_profile')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_valid_jwt_bearer_returns_200(self, api_client, teacher_user):
        refresh = RefreshToken.for_user(teacher_user)
        access = str(refresh.access_token)
        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        url = reverse('user_profile')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['user']['email'] == teacher_user.email
