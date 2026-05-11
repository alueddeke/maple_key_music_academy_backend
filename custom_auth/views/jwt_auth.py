from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import logging

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([AllowAny])
def get_jwt_token(request):
    """
    Get JWT token endpoint for username/password authentication

    This endpoint allows users to authenticate with email and password
    and receive JWT tokens for API access.

    Expected request body:
    {
        "email": "user@example.com",
        "password": "userpassword"
    }

    Returns:
    {
        "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
        "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
        "user": {
            "email": "user@example.com",
            "name": "User Name",
            "teacher_id": 1
        }
    }
    """
    from django.contrib.auth import authenticate
    from rest_framework_simplejwt.tokens import RefreshToken
    from django.contrib.auth import get_user_model
    from billing.models import UserRegistrationRequest

    User = get_user_model()

    # Get email and password from request
    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password')

    if not email or not password:
        return Response({
            'error': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Try to authenticate user
    user = authenticate(request, username=email, password=password)

    if user is None:
        # User doesn't exist - check if there's an approved registration request
        try:
            reg_request = UserRegistrationRequest.objects.get(email=email)

            if reg_request.status == 'approved':
                # Account was approved but user record does not exist yet.
                # The approval workflow sends an invitation link for the user to set
                # their own password via Google OAuth; there is no password-based
                # login path for email-registered users at this stage.
                return Response(
                    {
                        'error': 'Account setup incomplete',
                        'message': 'Your account was approved. Please use your invitation link to set up a password, or contact support.',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            elif reg_request.status == 'rejected':
                return Response({
                    'error': 'Registration rejected',
                    'message': 'Your registration request was rejected. Please contact support.'
                }, status=status.HTTP_403_FORBIDDEN)
            else:  # pending
                return Response({
                    'error': 'Approval pending',
                    'message': 'Your registration is pending management approval. You will be able to login once approved.'
                }, status=status.HTTP_403_FORBIDDEN)

        except UserRegistrationRequest.DoesNotExist:
            return Response({
                'error': 'Invalid email or password'
            }, status=status.HTTP_401_UNAUTHORIZED)

    # Check if user is approved
    if not user.is_approved:
        return Response({
            'error': 'Account not approved',
            'message': 'Your account is pending management approval. You will be able to login once approved.'
        }, status=status.HTTP_403_FORBIDDEN)

    # Generate JWT tokens for the authenticated user
    refresh = RefreshToken.for_user(user)

    # Check if user has the correct user_type (should be teacher or management)
    if not hasattr(user, 'user_type') or user.user_type not in ['teacher', 'management', 'student']:
        return Response({
            'error': 'Invalid account type',
            'message': 'This endpoint requires a teacher, student, or management account'
        }, status=status.HTTP_403_FORBIDDEN)

    # Get user name for response
    user_name = f"{user.first_name} {user.last_name}".strip()
    if not user_name:
        user_name = user.email

    return Response({
        'access_token': str(refresh.access_token),
        'refresh_token': str(refresh),
        'user': {
            'email': user.email,
            'name': user_name,
            'user_id': user.id,
            'user_type': user.user_type,
            'is_approved': user.is_approved
        }
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_jwt_token(request):
    """
    Refresh JWT token endpoint

    This endpoint allows users to get a new access token using their refresh token.
    This is useful when the access token expires (after 60 minutes in our case).

    Expected request body:
    {
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
    }

    Returns:
    {
        "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
        "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..." (if rotation enabled)
    }
    """
    from rest_framework_simplejwt.tokens import RefreshToken
    from rest_framework_simplejwt.exceptions import TokenError

    # Get refresh token from request
    refresh_token = request.data.get('refresh')

    if not refresh_token:
        return Response({
            'error': 'Refresh token is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Create RefreshToken object from the provided token string
        refresh = RefreshToken(refresh_token)

        # Generate new access token
        new_access_token = refresh.access_token

        # Check if we should rotate refresh tokens (from settings)
        from django.conf import settings
        if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS', False):
            # Blacklist the old refresh token and create a new one
            refresh.blacklist()
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.get(pk=refresh.payload['user_id'])
            new_refresh = RefreshToken.for_user(user)
            return Response({
                'access_token': str(new_access_token),
                'refresh_token': str(new_refresh)
            })
        else:
            # Just return new access token with same refresh token
            return Response({
                'access_token': str(new_access_token),
                'refresh_token': str(refresh)
            })

    except TokenError as e:
        return Response({
            'error': 'Invalid refresh token'
        }, status=status.HTTP_401_UNAUTHORIZED)
    except Exception as e:
        return Response({
            'error': 'Token refresh failed'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
