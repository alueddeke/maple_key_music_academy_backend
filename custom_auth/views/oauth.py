from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import requests
import os
import logging

logger = logging.getLogger(__name__)

GOOGLE_API_TIMEOUT = int(os.getenv('GOOGLE_API_TIMEOUT', '10'))


@api_view(['POST'])
@permission_classes([AllowAny])
def google_exchange(request):
    """
    POST /api/auth/google/exchange/
    Accepts { code, code_verifier } from frontend PKCE flow.
    Exchanges authorization code with Google server-to-server.
    Returns { access_token, refresh_token, user } in response body.
    Tokens are NEVER placed in URL params (SEC-01).
    """
    code = request.data.get('code', '').strip()
    code_verifier = request.data.get('code_verifier', '').strip()
    school_id = request.data.get('school_id')

    if not code or not code_verifier:
        return Response(
            {'error': 'code and code_verifier are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Exchange authorization code with Google (server-to-server)
    token_url = 'https://oauth2.googleapis.com/token'
    token_data = {
        'client_id': os.getenv('GOOGLE_CLIENT_ID'),
        'client_secret': os.getenv('GOOGLE_CLIENT_SECRET'),
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': f'{settings.FRONTEND_URL}/oauth-callback',  # must match frontend's redirect_uri
        'code_verifier': code_verifier,                    # PKCE verifier
    }
    try:
        token_response = requests.post(token_url, data=token_data, timeout=GOOGLE_API_TIMEOUT)
    except requests.exceptions.Timeout:
        logger.error('Google API timeout after %ds', GOOGLE_API_TIMEOUT)
        return Response(
            {'error': 'Google authentication timed out. Please try again.'},
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )

    if token_response.status_code != 200:
        logger.warning('Google token exchange failed: %s', token_response.text)
        return Response(
            {'error': 'Failed to exchange code with Google'},
            status=status.HTTP_400_BAD_REQUEST
        )

    token_info = token_response.json()
    access_token = token_info.get('access_token')

    # Get user info from Google
    user_info_url = 'https://www.googleapis.com/oauth2/v2/userinfo'
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        user_response = requests.get(user_info_url, headers=headers, timeout=GOOGLE_API_TIMEOUT)
    except requests.exceptions.Timeout:
        logger.error('Google API timeout after %ds', GOOGLE_API_TIMEOUT)
        return Response(
            {'error': 'Google authentication timed out. Please try again.'},
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )

    if user_response.status_code != 200:
        return Response(
            {'error': 'Failed to retrieve user info from Google'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user_data = user_response.json()
    user_email = user_data.get('email')

    # ===== INVITATION TOKEN FAST PATH =====
    # If frontend passes an invitation_token, bypass the standard approval workflow.
    # The invitation email must match the Google account email.
    invitation_token = request.data.get('invitation_token', '').strip()
    if invitation_token:
        from billing.models import InvitationToken
        User = get_user_model()
        try:
            invitation = InvitationToken.objects.get(token=invitation_token)
        except InvitationToken.DoesNotExist:
            return Response(
                {'error': 'Invalid invitation token'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not invitation.is_valid():
            return Response(
                {'error': 'Invitation token is expired or already used'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if invitation.email.lower() != user_email.lower():
            return Response(
                {'error': 'Google account email does not match invitation email'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            inv_user = User.objects.get(email=user_email)
        except User.DoesNotExist:
            school = getattr(getattr(getattr(invitation, 'approved_email', None), 'approved_by', None), 'school', None)
            if school is None:
                logger.error('Cannot derive school for invitation Google user: %s', user_email)
                return Response(
                    {'error': 'Server configuration error'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            inv_user = User.objects.create(
                email=invitation.email,
                first_name=user_data.get('given_name', ''),
                last_name=user_data.get('family_name', ''),
                user_type=invitation.user_type,
                oauth_provider='google',
                oauth_id=user_data.get('id'),
                is_approved=True,
                school=school,
            )
        invitation.mark_as_used()
        refresh = RefreshToken.for_user(inv_user)
        inv_name = f"{inv_user.first_name} {inv_user.last_name}".strip() or user_data.get('name', inv_user.email)
        return Response({
            'access_token': str(refresh.access_token),
            'refresh_token': str(refresh),
            'user': {
                'email': inv_user.email,
                'name': inv_name,
                'user_id': inv_user.id,
                'user_type': inv_user.user_type,
                'is_approved': inv_user.is_approved,
            },
        })

    # User find-or-create + approval workflow
    # Ported from google_oauth_callback (debug prints removed)
    User = get_user_model()
    from billing.models import ApprovedEmail, UserRegistrationRequest, School
    user = None

    exchange_school = None
    if school_id:
        try:
            exchange_school = School.objects.get(pk=school_id)
        except School.DoesNotExist:
            pass  # Optional field — invalid ID is silently ignored

    try:
        user = User.objects.get(email=user_email)
    except User.DoesNotExist:
        try:
            approved_email = ApprovedEmail.objects.get(email=user_email)
            school = getattr(getattr(approved_email, 'approved_by', None), 'school', None)
            if school is None:
                logger.error('Cannot derive school for ApprovedEmail user creation: %s', user_email)
                return Response(
                    {'error': 'Server configuration error'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            user = User.objects.create(
                email=user_email,
                first_name=user_data.get('given_name', ''),
                last_name=user_data.get('family_name', ''),
                user_type=approved_email.user_type,
                oauth_provider='google',
                oauth_id=user_data.get('id'),
                is_approved=True,
                school=school,
            )
        except ApprovedEmail.DoesNotExist:
            try:
                reg_request = UserRegistrationRequest.objects.get(email=user_email)
                if reg_request.status == 'approved':
                    # SEC-05: school derived from reviewer (reviewed_by is non-null when status='approved')
                    school = getattr(getattr(reg_request, 'reviewed_by', None), 'school', None)
                    if school is None:
                        logger.error('Cannot derive school for reg_request user creation: %s', user_email)
                        return Response(
                            {'error': 'Server configuration error'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        )
                    user = User.objects.create(
                        email=user_email,
                        first_name=user_data.get('given_name', ''),
                        last_name=user_data.get('family_name', ''),
                        user_type=reg_request.user_type,
                        oauth_provider='google',
                        oauth_id=user_data.get('id'),
                        is_approved=True,
                        school=school,
                    )
                elif reg_request.status == 'rejected':
                    return Response(
                        {
                            'error_code': 'registration_rejected',
                            'message': 'Registration rejected. Contact support.',
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )
                else:  # pending
                    return Response(
                        {
                            'error_code': 'approval_pending',
                            'message': 'Your registration is pending management approval.',
                        },
                        status=status.HTTP_202_ACCEPTED,
                    )
            except UserRegistrationRequest.DoesNotExist:
                UserRegistrationRequest.objects.create(
                    email=user_email,
                    first_name=user_data.get('given_name', ''),
                    last_name=user_data.get('family_name', ''),
                    user_type='teacher',  # default — management reassigns if needed
                    oauth_provider='google',
                    oauth_id=user_data.get('id'),
                    status='pending',
                    school=exchange_school,
                )
                return Response(
                    {
                        'error_code': 'new_registration',
                        'message': 'Thank you for registering! Await approval.',
                    },
                    status=status.HTTP_202_ACCEPTED,
                )
    except Exception as e:
        # Catch-all for unexpected DB errors during user find-or-create flow
        logger.exception('Google exchange approval flow error')
        return Response(
            {'error': f'Approval flow error: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Reject unapproved users before issuing any token
    if not user.is_approved:
        return Response(
            {
                'error_code': 'approval_pending',
                'message': 'Your account is pending management approval.',
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # Successful user found or created — issue JWT
    refresh = RefreshToken.for_user(user)

    user_name = f"{user.first_name} {user.last_name}".strip()
    if not user_name:
        user_name = user_data.get('name', user.email)

    return Response({
        'access_token': str(refresh.access_token),
        'refresh_token': str(refresh),
        'user': {
            'email': user.email,
            'name': user_name,
            'user_id': user.id,
            'user_type': user.user_type,
            'is_approved': user.is_approved,
        }
    })
