from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


# INVITATION TOKEN ENDPOINTS

@api_view(['GET'])
@permission_classes([AllowAny])  # Public endpoint - no authentication required
def validate_invitation_token(request, token):
    """Validate invitation token and return email/user_type if valid"""
    from ..models import InvitationToken

    try:
        invitation = InvitationToken.objects.get(token=token)

        if not invitation.is_valid():
            return Response({
                'error': 'Invalid or expired invitation token',
                'is_used': invitation.is_used,
                'is_expired': timezone.now() >= invitation.expires_at
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'valid': True,
            'email': invitation.email,
            'user_type': invitation.user_type,
            'user_type_display': invitation.get_user_type_display(),
            'expires_at': invitation.expires_at
        })

    except InvitationToken.DoesNotExist:
        return Response({
            'error': 'Invalid invitation token'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([AllowAny])  # Public endpoint - no authentication required
def setup_account_with_invitation(request, token):
    """Create user account using invitation token"""
    from ..models import InvitationToken, User

    try:
        invitation = InvitationToken.objects.get(token=token)

        # Validate token
        if not invitation.is_valid():
            return Response({
                'error': 'Invalid or expired invitation token'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check if user already exists
        if User.objects.filter(email=invitation.email).exists():
            return Response({
                'error': 'An account with this email already exists'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Get user data from request
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        password = request.data.get('password')

        if not first_name or not last_name or not password:
            return Response({
                'error': 'First name, last name, and password are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Create user account — derive school from invitation chain (never use School.objects.first())
        school = getattr(getattr(getattr(invitation, 'approved_email', None), 'approved_by', None), 'school', None)
        if school is None:
            logger.error(
                'Cannot derive school for invitation user creation: %s',
                invitation.approved_email.email if invitation.approved_email else '<unknown>'
            )
            return Response(
                {'error': 'Server configuration error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        user = User.objects.create_user(
            email=invitation.email,
            password=password if password else None,  # Password is optional (for OAuth users)
            first_name=first_name,
            last_name=last_name,
            user_type=invitation.user_type,
            school=school
        )
        user.is_approved = True  # Pre-approved via invitation
        user.save()

        # Mark token as used
        invitation.mark_as_used()

        # Generate JWT tokens for immediate login
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)

        return Response({
            'message': 'Account created successfully',
            'user': {
                'email': user.email,
                'name': user.get_full_name(),
                'user_id': user.id,
                'user_type': user.user_type,
                'is_approved': user.is_approved
            },
            'access_token': str(refresh.access_token),
            'refresh_token': str(refresh)
        }, status=status.HTTP_201_CREATED)

    except InvitationToken.DoesNotExist:
        return Response({
            'error': 'Invalid invitation token'
        }, status=status.HTTP_404_NOT_FOUND)
