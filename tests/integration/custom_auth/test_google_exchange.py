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
from billing.models import ApprovedEmail, UserRegistrationRequest, InvitationToken
from django.utils import timezone
import datetime

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

        with patch('custom_auth.views.oauth.requests.post', return_value=mock_token), \
             patch('custom_auth.views.oauth.requests.get', return_value=mock_userinfo):
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

        with patch('custom_auth.views.oauth.requests.post', return_value=mock_token), \
             patch('custom_auth.views.oauth.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz',
            }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data.get('error_code') == 'registration_rejected'

    def test_google_timeout_returns_504(self, api_client, school):
        """
        SEC-02: requests.post to Google token endpoint raises Timeout.
        Expects HTTP 504 Gateway Timeout (not 400 or 500).
        """
        import requests as req_lib

        with patch('custom_auth.views.oauth.requests.post',
                   side_effect=req_lib.exceptions.Timeout):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough_for_validation',
            }, format='json')

        assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        assert 'timed out' in response.data.get('error', '').lower()

    def test_google_exchange_creates_user_in_approver_school(
        self, api_client, school, second_school
    ):
        """
        SEC-05: When google_exchange creates a new user from an ApprovedEmail,
        the user's school MUST equal ApprovedEmail.approved_by.school — NOT
        School.objects.first(). This test seeds the approver in `second_school`
        and asserts the new user lands in `second_school` regardless of
        which school is "first" in the DB.
        """
        # Approver belongs to second_school (NOT the default 'school' fixture)
        approver = User.objects.create_user(
            email='approver_s2@example.com',
            password='test123',
            user_type='management',
            school=second_school,
            is_approved=True,
        )
        ApprovedEmail.objects.create(
            email='new_oauth_user@example.com',
            approved_by=approver,
        )

        mock_token, mock_userinfo = self._mock_google_responses(
            'new_oauth_user@example.com'
        )

        with patch('custom_auth.views.oauth.requests.post', return_value=mock_token), \
             patch('custom_auth.views.oauth.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough_for_validation',
            }, format='json')

        assert response.status_code == status.HTTP_200_OK
        created_user = User.objects.get(email='new_oauth_user@example.com')
        assert created_user.school_id == second_school.id, (
            f'User school must be derived from ApprovedEmail.approved_by.school '
            f'(expected {second_school.id}, got {created_user.school_id}). '
            f'If this fails with school.id, google_exchange is still using '
            f'School.objects.first() (SEC-05 not yet fixed).'
        )

    def test_unapproved_existing_user_returns_403(self, api_client, unapproved_teacher):
        """
        LOCK-01 / BUG-01: Existing user with is_approved=False calls google_exchange.
        Must receive 403 with error_code='approval_pending' — no JWT issued.
        The is_approved guard lives at custom_auth/views.py:187.
        """
        mock_token, mock_userinfo = self._mock_google_responses(
            unapproved_teacher.email,
            google_id='google_unapproved_id_456',
        )

        with patch('custom_auth.views.oauth.requests.post', return_value=mock_token), \
             patch('custom_auth.views.oauth.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
            }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data.get('error_code') == 'approval_pending'
        assert 'access_token' not in response.data
        assert 'refresh_token' not in response.data


@pytest.mark.django_db
class TestGoogleExchangeInvitationFastPath:
    """
    Integration tests for the invitation_token fast path in POST /api/auth/google/exchange/.

    The invitation fast path (oauth.py lines 87-144) allows a pre-approved user to
    complete account setup by supplying an InvitationToken alongside their Google auth
    code, bypassing the standard approval workflow.
    """

    URL = 'google_exchange'

    def _mock_google_responses(self, email: str, google_id: str = 'inv_google_id_001'):
        """Helper: build mock objects for Google token + userinfo endpoints."""
        mock_token = MagicMock()
        mock_token.status_code = 200
        mock_token.json.return_value = {'access_token': 'google_access_token_inv'}

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

    def _make_invitation(self, email, approver, user_type='teacher', expired=False, used=False):
        """Helper: create an ApprovedEmail + InvitationToken for the given email."""
        approved_email = ApprovedEmail.objects.create(
            email=email,
            user_type=user_type,
            approved_by=approver,
        )
        expires_at = (
            timezone.now() - datetime.timedelta(hours=1)  # already expired
            if expired
            else timezone.now() + datetime.timedelta(hours=48)
        )
        token = InvitationToken.objects.create(
            email=email,
            token=f'test-token-{email.replace("@", "-").replace(".", "-")}',
            user_type=user_type,
            approved_email=approved_email,
            expires_at=expires_at,
            is_used=used,
        )
        return token

    def test_valid_invitation_new_user_creates_user_and_returns_jwt(self, api_client, school, management_user):
        """
        Valid invitation token + new user: the view creates a User record and issues JWT tokens.
        """
        email = 'invited.teacher@example.com'
        token = self._make_invitation(email, approver=management_user)

        mock_token, mock_userinfo = self._mock_google_responses(email)

        with patch('custom_auth.views.oauth.requests.post', return_value=mock_token), \
             patch('custom_auth.views.oauth.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
                'invitation_token': token.token,
            }, format='json')

        assert response.status_code == status.HTTP_200_OK, response.data
        assert 'access_token' in response.data
        assert 'refresh_token' in response.data
        assert response.data['user']['email'] == email
        assert response.data['user']['user_type'] == 'teacher'
        assert response.data['user']['is_approved'] is True

        created_user = User.objects.get(email=email)
        assert created_user.school == school
        assert created_user.is_approved is True

        token.refresh_from_db()
        assert token.is_used is True

    def test_valid_invitation_existing_unapproved_user_returns_403(
        self, api_client, school, management_user, unapproved_teacher
    ):
        """
        Valid invitation token + existing unapproved user: must return 403.
        The is_approved guard added by CR-01 must fire before JWT issuance.
        """
        token = self._make_invitation(
            unapproved_teacher.email, approver=management_user, user_type='teacher'
        )

        mock_token, mock_userinfo = self._mock_google_responses(unapproved_teacher.email)

        with patch('custom_auth.views.oauth.requests.post', return_value=mock_token), \
             patch('custom_auth.views.oauth.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
                'invitation_token': token.token,
            }, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data.get('error_code') == 'approval_pending'
        assert 'access_token' not in response.data
        assert 'refresh_token' not in response.data

    def test_expired_invitation_token_returns_400(self, api_client, school, management_user):
        """
        Expired invitation token: the view must return 400 before creating any user or JWT.
        """
        email = 'expired.invite@example.com'
        token = self._make_invitation(email, approver=management_user, expired=True)

        mock_token, mock_userinfo = self._mock_google_responses(email)

        with patch('custom_auth.views.oauth.requests.post', return_value=mock_token), \
             patch('custom_auth.views.oauth.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
                'invitation_token': token.token,
            }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'access_token' not in response.data
        assert User.objects.filter(email=email).count() == 0

    def test_used_invitation_token_returns_400(self, api_client, school, management_user):
        """
        Already-used invitation token: the view must return 400.
        """
        email = 'used.invite@example.com'
        token = self._make_invitation(email, approver=management_user, used=True)

        mock_token, mock_userinfo = self._mock_google_responses(email)

        with patch('custom_auth.views.oauth.requests.post', return_value=mock_token), \
             patch('custom_auth.views.oauth.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
                'invitation_token': token.token,
            }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'access_token' not in response.data

    def test_email_mismatch_invitation_returns_400(self, api_client, school, management_user):
        """
        Invitation token email does not match the Google account email: must return 400.
        """
        email = 'correct.email@example.com'
        wrong_email = 'wrong.email@example.com'
        token = self._make_invitation(email, approver=management_user)

        # Google returns wrong_email but the invitation is for email
        mock_token, mock_userinfo = self._mock_google_responses(wrong_email)

        with patch('custom_auth.views.oauth.requests.post', return_value=mock_token), \
             patch('custom_auth.views.oauth.requests.get', return_value=mock_userinfo):
            url = reverse(self.URL)
            response = api_client.post(url, {
                'code': 'auth_code_abc',
                'code_verifier': 'verifier_xyz_long_enough',
                'invitation_token': token.token,
            }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'access_token' not in response.data
        assert User.objects.filter(email=wrong_email).count() == 0
