from django.shortcuts import redirect, render
from allauth.socialaccount.providers.google.views import oauth2_login, GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from allauth.socialaccount.providers.oauth2.views import OAuth2LoginView
from allauth.socialaccount.models import SocialLogin
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import requests


@api_view(['GET','POST'])
@permission_classes([AllowAny])
def google_oauth(request):
    """redirect to google for oauth flow"""
    return oauth2_login(request, 'google')



@api_view(['GET'])
@permission_classes([AllowAny])
def google_oauth_callback(request):
    """Google OAuth callback endpoint"""
    try:
        # Step 1: Get the authorization code from the request
        code = request.GET.get('code')
        if not code:
            return Response({'error': 'No authorization code provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Step 2: Get Google OAuth app configuration
        from allauth.socialaccount.models import SocialApp
        try:
            app = SocialApp.objects.get(provider='google')
        except SocialApp.DoesNotExist:
            return Response({'error': 'Google OAuth app not configured. Please set up in Django admin.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Step 3: Exchange code for tokens using Google API directly
        token_url = 'https://oauth2.googleapis.com/token'
        token_data = {
            'client_id': app.client_id,
            'client_secret': app.secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': 'http://localhost:8000/api/auth/google/callback/'
        }
        
        token_response = requests.post(token_url, data=token_data)
        if token_response.status_code != 200:
            return Response({'error': 'Failed to exchange code for token'}, status=status.HTTP_400_BAD_REQUEST)
        
        token_info = token_response.json()
        access_token = token_info.get('access_token')
        
        # Step 4: Get user info from Google
        user_info_url = 'https://www.googleapis.com/oauth2/v2/userinfo'
        headers = {'Authorization': f'Bearer {access_token}'}
        user_response = requests.get(user_info_url, headers=headers)
        
        if user_response.status_code != 200:
            return Response({'error': 'Failed to get user info from Google'}, status=status.HTTP_400_BAD_REQUEST)
        
        user_data = user_response.json()
        
        # Step 5: Get or create User (unified model)
        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=user_data.get('email'),
            defaults={
                'username': user_data.get('email'),
                'first_name': user_data.get('given_name', ''),
                'last_name': user_data.get('family_name', ''),
                'user_type': 'teacher',  # Default to teacher for OAuth
                'oauth_provider': 'google',
                'oauth_id': user_data.get('id'),
                'is_approved': False,  # Requires management approval
            }
        )
        
        # Step 7: Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        # Get user name from Google data or use email as fallback
        user_name = f"{user.first_name} {user.last_name}".strip()
        if not user_name:
            user_name = user_data.get('name', user.email)  # Use Google's name or email
        
        return Response({
            'message': 'OAuth successful',
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
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

 

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
    
    User = get_user_model()
    
    # Get email and password from request
    email = request.data.get('email')
    password = request.data.get('password')
    
    if not email or not password:
        return Response({
            'error': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Authenticate user using Django's built-in authentication
    # This checks the email/password against the database
    user = authenticate(request, username=email, password=password)
    
    if user is None:
        return Response({
            'error': 'Invalid email or password'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Generate JWT tokens for the authenticated user
    refresh = RefreshToken.for_user(user)
    
    # Check if user has the correct user_type (should be teacher for this endpoint)
    if not hasattr(user, 'user_type') or user.user_type not in ['teacher', 'management']:
        return Response({
            'error': 'Invalid account type',
            'message': 'This endpoint requires a teacher or management account'
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
            new_refresh = RefreshToken.for_user(refresh.payload['user_id'])
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

@api_view(['GET'])
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
    from rest_framework.permissions import IsAuthenticated
    from rest_framework.decorators import permission_classes
    
    # Check if user is authenticated
    if not request.user.is_authenticated:
        return Response({
            'error': 'Authentication required'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
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
