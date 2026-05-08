"""
Integration tests for invitation token endpoints (billing/views/invitation.py).
Requirement: TST-04

Endpoints covered:
- GET  /api/billing/invite/<token>/validate/ (validate_invitation_token)
- POST /api/billing/invite/<token>/setup/    (setup_account_with_invitation)
"""
import secrets
from datetime import timedelta
import pytest
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import status
from billing.models import ApprovedEmail, InvitationToken

User = get_user_model()


def _make_invitation(email, approved_by, *, expires_in_days=7, is_used=False):
    """Helper: create an ApprovedEmail + InvitationToken pair for tests."""
    approved_email = ApprovedEmail.objects.create(email=email, approved_by=approved_by)
    invitation = InvitationToken.objects.create(
        email=email,
        token=secrets.token_urlsafe(32),
        user_type='teacher',
        approved_email=approved_email,
        expires_at=timezone.now() + timedelta(days=expires_in_days),
        is_used=is_used,
    )
    return invitation


@pytest.mark.django_db
class TestInvitationTokenValidate:
    """Tests for GET /api/billing/invite/<token>/validate/ (validate_invitation_token)."""

    def test_valid_token_returns_200(self, api_client, management_user):
        """Valid token returns 200 with valid=True, email, and user_type."""
        inv = _make_invitation('newhire@example.com', management_user)

        url = reverse('validate_invitation_token', kwargs={'token': inv.token})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['valid'] is True
        assert response.data['email'] == 'newhire@example.com'
        assert response.data['user_type'] == 'teacher'

    def test_expired_token_returns_400(self, api_client, management_user):
        """Expired token returns 400 with is_expired=True."""
        inv = _make_invitation('expired@example.com', management_user, expires_in_days=-1)

        url = reverse('validate_invitation_token', kwargs={'token': inv.token})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['is_expired'] is True

    def test_used_token_returns_400(self, api_client, management_user):
        """Used token returns 400 with is_used=True."""
        inv = _make_invitation('used@example.com', management_user, is_used=True)

        url = reverse('validate_invitation_token', kwargs={'token': inv.token})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['is_used'] is True

    def test_unknown_token_returns_404(self, api_client):
        """Non-existent token returns 404."""
        url = reverse('validate_invitation_token', kwargs={'token': 'nonexistent-token-xyz'})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestInvitationTokenSetup:
    """Tests for POST /api/billing/invite/<token>/setup/ (setup_account_with_invitation)."""

    def test_valid_setup_creates_user_and_returns_jwt(self, api_client, management_user):
        """Valid setup creates user, returns JWT tokens, and marks token as used."""
        inv = _make_invitation('setup@example.com', management_user)

        url = reverse('setup_account_with_invitation', kwargs={'token': inv.token})
        response = api_client.post(url, {
            'first_name': 'Set',
            'last_name': 'Up',
            'password': 'StrongPass!1',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert 'access_token' in response.data
        assert 'refresh_token' in response.data
        assert User.objects.filter(email='setup@example.com').exists()

        inv.refresh_from_db()
        assert inv.is_used is True

    def test_setup_assigns_school_from_invitation_chain(self, api_client, management_user, second_school):
        """User school is derived from invitation.approved_email.approved_by.school (not School.objects.first)."""
        s2_mgmt = User.objects.create_user(
            email='s2_mgmt@test.com',
            password='x',
            user_type='management',
            school=second_school,
            is_approved=True,
        )
        inv = _make_invitation('cross@example.com', s2_mgmt)

        url = reverse('setup_account_with_invitation', kwargs={'token': inv.token})
        response = api_client.post(url, {
            'first_name': 'Cross',
            'last_name': 'School',
            'password': 'StrongPass!1',
        }, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        created_user = User.objects.get(email='cross@example.com')
        assert created_user.school_id == second_school.id, (
            f'User school must be derived from invitation chain '
            f'(expected {second_school.id}, got {created_user.school_id}). '
            f'SEC-05 invariant violated.'
        )

    def test_setup_with_expired_token_returns_400(self, api_client, management_user):
        """Expired token setup returns 400 and no user is created."""
        inv = _make_invitation('expired_setup@example.com', management_user, expires_in_days=-1)

        url = reverse('setup_account_with_invitation', kwargs={'token': inv.token})
        response = api_client.post(url, {
            'first_name': 'Expired',
            'last_name': 'User',
            'password': 'StrongPass!1',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not User.objects.filter(email='expired_setup@example.com').exists()

    def test_setup_with_used_token_returns_400(self, api_client, management_user):
        """Already-used token setup returns 400 and no user is created."""
        inv = _make_invitation('used_setup@example.com', management_user, is_used=True)

        url = reverse('setup_account_with_invitation', kwargs={'token': inv.token})
        response = api_client.post(url, {
            'first_name': 'Used',
            'last_name': 'Token',
            'password': 'StrongPass!1',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not User.objects.filter(email='used_setup@example.com').exists()

    def test_setup_missing_first_name_returns_400(self, api_client, management_user):
        """Missing first_name returns 400."""
        inv = _make_invitation('partial@example.com', management_user)

        url = reverse('setup_account_with_invitation', kwargs={'token': inv.token})
        response = api_client.post(url, {
            'last_name': 'X',
            'password': 'StrongPass!1',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_setup_missing_last_name_returns_400(self, api_client, management_user):
        """Missing last_name returns 400."""
        inv = _make_invitation('partial2@example.com', management_user)

        url = reverse('setup_account_with_invitation', kwargs={'token': inv.token})
        response = api_client.post(url, {
            'first_name': 'X',
            'password': 'StrongPass!1',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_setup_missing_password_returns_400(self, api_client, management_user):
        """Missing password returns 400."""
        inv = _make_invitation('partial3@example.com', management_user)

        url = reverse('setup_account_with_invitation', kwargs={'token': inv.token})
        response = api_client.post(url, {
            'first_name': 'X',
            'last_name': 'Y',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_setup_when_user_already_exists_returns_400(self, api_client, management_user):
        """Duplicate email setup returns 400 and exactly one user remains."""
        User.objects.create_user(
            email='collide@example.com',
            user_type='teacher',
            school=management_user.school,
            is_approved=True,
        )
        inv = _make_invitation('collide@example.com', management_user)

        url = reverse('setup_account_with_invitation', kwargs={'token': inv.token})
        response = api_client.post(url, {
            'first_name': 'Collide',
            'last_name': 'User',
            'password': 'StrongPass!1',
        }, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # No duplicate created — still exactly one user with this email
        assert User.objects.filter(email='collide@example.com').count() == 1
