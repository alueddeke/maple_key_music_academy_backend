"""
Integration tests for the OAuth approval-flow branches in google_exchange.
Requirement: TST-02

These tests cover the user-resolution decision tree:
  existing user -> ApprovedEmail -> UserRegistrationRequest (3 statuses) -> brand new

For PKCE correctness, timeout handling, and school derivation see
test_google_exchange.py (SEC-01/02/05).
"""
import pytest
from unittest.mock import patch, MagicMock
from django.urls import reverse
from rest_framework import status
from django.contrib.auth import get_user_model
from billing.models import ApprovedEmail, UserRegistrationRequest

User = get_user_model()


@pytest.mark.django_db
class TestGoogleOAuthFlow:
    """Integration tests for google_exchange approval-flow branches (TST-02)."""

    def _mock_google_responses(self, email: str, google_id: str = 'google_id_123'):
        """Helper: build mock objects for Google token + userinfo endpoints."""
        mock_token = MagicMock()
        mock_token.status_code = 200
        mock_token.json.return_value = {'access_token': 'fake_google_access_token'}

        parts = email.split('@')[0].split('.')
        given = parts[0].capitalize()
        family = parts[1].capitalize() if len(parts) > 1 else 'User'

        mock_userinfo = MagicMock()
        mock_userinfo.status_code = 200
        mock_userinfo.json.return_value = {
            'email': email,
            'given_name': given,
            'family_name': family,
            'id': google_id,
            'name': f'{given} {family}',
        }
        return mock_token, mock_userinfo

    def test_existing_approved_user_returns_jwt(self, api_client, school):
        """
        Existing approved user with no ApprovedEmail or reg_request row is
        resolved by User.objects.get(email=...) and receives 200 + JWT tokens.
        No new User row must be created.
        """
        User.objects.create_user(
            email='returning@example.com',
            user_type='teacher',
            school=school,
            is_approved=True,
            first_name='Re',
            last_name='Turn',
            password=None,
        )
        user_count_before = User.objects.count()

        mock_token, mock_userinfo = self._mock_google_responses('returning@example.com')
        with patch('custom_auth.views.requests.post', return_value=mock_token), \
             patch('custom_auth.views.requests.get', return_value=mock_userinfo):
            response = api_client.post(reverse('google_exchange'), {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'access_token' in response.data
        assert 'refresh_token' in response.data
        assert response.data['user']['email'] == 'returning@example.com'
        # No new user was created
        assert User.objects.count() == user_count_before

    def test_preapproved_email_creates_user_and_returns_jwt(self, api_client, school, management_user):
        """
        Email on ApprovedEmail list creates a new approved User in the approver's
        school and returns 200 + JWT tokens (SEC-05 school derivation re-asserted).
        """
        ApprovedEmail.objects.create(
            email='preapproved@example.com',
            approved_by=management_user,
        )

        mock_token, mock_userinfo = self._mock_google_responses('preapproved@example.com')
        with patch('custom_auth.views.requests.post', return_value=mock_token), \
             patch('custom_auth.views.requests.get', return_value=mock_userinfo):
            response = api_client.post(reverse('google_exchange'), {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'access_token' in response.data
        assert 'refresh_token' in response.data
        assert User.objects.filter(email='preapproved@example.com').exists()
        new_user = User.objects.get(email='preapproved@example.com')
        assert new_user.is_approved is True
        assert new_user.school_id == management_user.school_id

    def test_approved_registration_request_creates_user(self, api_client, school, management_user):
        """
        UserRegistrationRequest with status='approved' creates a new User in the
        reviewer's school and returns 200 + JWT tokens.
        """
        UserRegistrationRequest.objects.create(
            email='approved_reg@example.com',
            first_name='AR',
            last_name='User',
            user_type='teacher',
            status='approved',
            reviewed_by=management_user,
        )

        mock_token, mock_userinfo = self._mock_google_responses('approved_reg@example.com')
        with patch('custom_auth.views.requests.post', return_value=mock_token), \
             patch('custom_auth.views.requests.get', return_value=mock_userinfo):
            response = api_client.post(reverse('google_exchange'), {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'access_token' in response.data
        assert 'refresh_token' in response.data
        assert User.objects.filter(email='approved_reg@example.com').exists()
        created_user = User.objects.get(email='approved_reg@example.com')
        assert created_user.school_id == management_user.school_id

    def test_pending_registration_request_returns_202_approval_pending(self, api_client, school):
        """
        UserRegistrationRequest with status='pending' returns 202 with
        error_code='approval_pending'. No User row is created.
        """
        UserRegistrationRequest.objects.create(
            email='pending@example.com',
            first_name='P',
            last_name='R',
            user_type='teacher',
            status='pending',
        )

        mock_token, mock_userinfo = self._mock_google_responses('pending@example.com')
        with patch('custom_auth.views.requests.post', return_value=mock_token), \
             patch('custom_auth.views.requests.get', return_value=mock_userinfo):
            response = api_client.post(reverse('google_exchange'), {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
            }, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data.get('error_code') == 'approval_pending'
        assert not User.objects.filter(email='pending@example.com').exists()

    def test_new_email_creates_registration_request_returns_202(self, api_client, school):
        """
        Brand-new email with no User and no UserRegistrationRequest creates a
        pending reg_request and returns 202 with error_code='new_registration'.
        No User row is created.
        """
        # Pre-condition: nothing exists for this email
        assert not User.objects.filter(email='brand_new@example.com').exists()
        assert not UserRegistrationRequest.objects.filter(email='brand_new@example.com').exists()

        mock_token, mock_userinfo = self._mock_google_responses('brand_new@example.com')
        with patch('custom_auth.views.requests.post', return_value=mock_token), \
             patch('custom_auth.views.requests.get', return_value=mock_userinfo):
            response = api_client.post(reverse('google_exchange'), {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
            }, format='json')

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data.get('error_code') == 'new_registration'
        assert UserRegistrationRequest.objects.filter(
            email='brand_new@example.com', status='pending'
        ).exists()
        assert not User.objects.filter(email='brand_new@example.com').exists()

    def test_google_token_endpoint_failure_returns_400(self, api_client, school):
        """
        Non-200 from Google's token endpoint returns 400 with an error message
        about failing to exchange the code. The userinfo endpoint is never reached.
        """
        mock_token = MagicMock()
        mock_token.status_code = 400
        mock_token.text = 'invalid_grant'
        mock_token.json.return_value = {'error': 'invalid_grant'}

        with patch('custom_auth.views.requests.post', return_value=mock_token):
            response = api_client.post(reverse('google_exchange'), {
                'code': 'bad_code',
                'code_verifier': 'verifier_xyz_long_enough',
            }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data.get('error') == 'Failed to exchange code with Google'

    def test_google_userinfo_failure_returns_400(self, api_client, school):
        """
        200 from token endpoint but non-200 from userinfo endpoint returns 400
        with an error message about failing to retrieve user info.
        """
        mock_token = MagicMock()
        mock_token.status_code = 200
        mock_token.json.return_value = {'access_token': 'tok'}

        mock_userinfo = MagicMock()
        mock_userinfo.status_code = 401

        with patch('custom_auth.views.requests.post', return_value=mock_token), \
             patch('custom_auth.views.requests.get', return_value=mock_userinfo):
            response = api_client.post(reverse('google_exchange'), {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
            }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data.get('error') == 'Failed to retrieve user info from Google'
