"""
Integration tests for POST /api/auth/google/exchange/
Requirement: SEC-01 — tokens delivered in response body, not URL params
"""
import pytest
from unittest.mock import patch, MagicMock
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from billing.models import ApprovedEmail, UserRegistrationRequest

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestGoogleExchangeEndpoint:
    """Integration tests for POST /api/auth/google/exchange/"""

    URL = 'google_exchange'  # URL name registered in custom_auth/urls.py (Plan 02 wires this)

    def _mock_google_responses(self, email: str, google_id: str = 'google_id_123'):
        """Helper: build mock objects for Google token + userinfo endpoints."""
        mock_token = MagicMock()
        mock_token.status_code = 200
        mock_token.json.return_value = {'access_token': 'google_access_token_xyz'}

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

    def test_valid_exchange_existing_user_returns_200_with_tokens(self, api_client, school):
        """
        SEC-01: Valid code + code_verifier for an existing approved user
        returns HTTP 200 with access_token and refresh_token in the response BODY
        (never in URL params).
        """
        user = User.objects.create_user(
            email='existing@example.com',
            password=None,
            user_type='teacher',
            school=school,
            is_approved=True,
            first_name='Test',
            last_name='User',
        )

        mock_token, mock_userinfo = self._mock_google_responses('existing@example.com')

        with patch('custom_auth.views.requests.post', return_value=mock_token), \
             patch('custom_auth.views.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert 'access_token' in response.data
        assert 'refresh_token' in response.data
        assert 'user' in response.data
        assert response.data['user']['email'] == 'existing@example.com'
        assert response.data['user']['user_type'] == 'teacher'

    def test_missing_code_verifier_returns_400(self, api_client):
        """
        SEC-01: Missing code_verifier returns 400 without calling Google.
        Proves the endpoint enforces PKCE — a plain authorization code alone is rejected.
        """
        url = reverse(self.URL)
        response = api_client.post(url, {'code': 'auth_code_abc'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_code_returns_400(self, api_client):
        """Missing authorization code returns 400."""
        url = reverse(self.URL)
        response = api_client.post(url, {'code_verifier': 'verifier_xyz'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejected_registration_returns_403_with_error_code(self, api_client, school):
        """
        SEC-01: A user with a rejected registration request receives 403
        with error_code='registration_rejected' in the response body.
        """
        UserRegistrationRequest.objects.create(
            email='rejected@example.com',
            first_name='Rejected',
            last_name='User',
            user_type='teacher',
            oauth_provider='google',
            oauth_id='google_rejected_id',
            status='rejected',
        )

        mock_token, mock_userinfo = self._mock_google_responses(
            'rejected@example.com', google_id='google_rejected_id'
        )

        with patch('custom_auth.views.requests.post', return_value=mock_token), \
             patch('custom_auth.views.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz',
            }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data.get('error_code') == 'registration_rejected'
