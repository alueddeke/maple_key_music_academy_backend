from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_profile(request):
    """
    Get current user profile endpoint

    This endpoint returns information about the currently authenticated user.
    It requires a valid JWT access token in the Authorization header.

    Expected headers:
    Authorization: Bearer <access_token>

    Returns:
    {
        "user": {
            "email": "user@example.com",
            "name": "User Name",
            "teacher_id": 1,
            "first_name": "User",
            "last_name": "Name"
        },
        "teacher": {
            "id": 1,
            "name": "User Name",
            "email": "user@example.com",
            "address": "123 Main St",
            "phoneNumber": "555-1234"
        }
    }
    """
    # Get user name
    user_name = f"{request.user.first_name} {request.user.last_name}".strip()
    if not user_name:
        user_name = request.user.email

    return Response({
        'user': {
            'email': request.user.email,
            'name': user_name,
            'user_id': request.user.id,
            'user_type': request.user.user_type,
            'is_approved': request.user.is_approved,
            'first_name': request.user.first_name,
            'last_name': request.user.last_name,
            'phone_number': request.user.phone_number,
            'address': request.user.address,
            'bio': getattr(request.user, 'bio', ''),
            'instruments': getattr(request.user, 'instruments', ''),
            'hourly_rate': getattr(request.user, 'hourly_rate', None),
        }
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def logout(request):
    """
    Logout endpoint

    This endpoint blacklists the provided refresh token, effectively logging out the user.
    Once a refresh token is blacklisted, it cannot be used to get new access tokens.

    Expected request body:
    {
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
    }

    Returns:
    {
        "message": "Successfully logged out"
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
        # Create RefreshToken object and blacklist it
        refresh = RefreshToken(refresh_token)
        refresh.blacklist()

        return Response({
            'message': 'Successfully logged out'
        })

    except TokenError as e:
        return Response({
            'error': 'Invalid refresh token'
        }, status=status.HTTP_401_UNAUTHORIZED)
    except Exception as e:
        return Response({
            'error': 'Logout failed'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
