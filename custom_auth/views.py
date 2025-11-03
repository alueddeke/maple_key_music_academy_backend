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
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from urllib.parse import urlencode
import requests
import os

# Get URLs from environment
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')
# For backend callback URL, construct from request in the view since it needs to match environment


@csrf_exempt
@api_view(['GET','POST'])
@permission_classes([AllowAny])
def google_oauth(request):
    """redirect to google for oauth flow"""
    # Get frontend redirect URI - pass it via OAuth state parameter instead of session
    # This avoids session cookie issues that cause redirect loops
    default_frontend_redirect = f'{FRONTEND_URL}/oauth-callback'
    frontend_redirect_uri = request.GET.get('redirect_uri', default_frontend_redirect)

    # Build Google OAuth URL manually
    import json
    import base64

    # Encode frontend redirect URI in state parameter (OAuth standard approach)
    state_data = {'redirect_uri': frontend_redirect_uri}
    state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

    # Get Google OAuth app configuration
    from allauth.socialaccount.models import SocialApp
    try:
        app = SocialApp.objects.get(provider='google')
    except SocialApp.DoesNotExist:
        return Response({'error': 'Google OAuth app not configured. Please set up in Django admin.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Construct backend callback URL from request to match environment
    backend_callback_url = request.build_absolute_uri('/api/auth/google/callback/')

    print(f"DEBUG: Backend callback URL: {backend_callback_url}")
    print(f"DEBUG: Request host: {request.get_host()}")
    print(f"DEBUG: Request scheme: {request.scheme}")

    google_oauth_url = 'https://accounts.google.com/o/oauth2/v2/auth'
    params = {
        'client_id': app.client_id,
        'redirect_uri': backend_callback_url,
        'scope': 'email profile',
        'response_type': 'code',
        'access_type': 'online',
        'state': state  # Pass redirect URI via state parameter
    }

    redirect_url = f"{google_oauth_url}?{urlencode(params)}"
    print(f"DEBUG: Full OAuth URL: {redirect_url}")
    return HttpResponseRedirect(redirect_url)



@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def google_oauth_callback(request):
    """Google OAuth callback endpoint"""
    import logging
    import sys
    logger = logging.getLogger(__name__)

    # Force output to stderr immediately
    sys.stderr.write(f"=== OAuth Callback Started ===\n")
    sys.stderr.flush()

    try:
        # Step 1: Get the authorization code and state from the request
        code = request.GET.get('code')
        state = request.GET.get('state')

        sys.stderr.write(f"Code present: {bool(code)}\n")
        sys.stderr.flush()

        if not code:
            return Response({'error': 'No authorization code provided'}, status=status.HTTP_400_BAD_REQUEST)

        # Decode state parameter to get frontend redirect URI
        import json
        import base64
        default_frontend_redirect = f'{FRONTEND_URL}/oauth-callback'
        try:
            state_data = json.loads(base64.urlsafe_b64decode(state).decode()) if state else {}
            frontend_redirect_uri = state_data.get('redirect_uri', default_frontend_redirect)
        except:
            frontend_redirect_uri = default_frontend_redirect

        # Step 2: Get Google OAuth app configuration
        from allauth.socialaccount.models import SocialApp
        try:
            app = SocialApp.objects.get(provider='google')
        except SocialApp.DoesNotExist:
            return Response({'error': 'Google OAuth app not configured. Please set up in Django admin.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Step 3: Exchange code for tokens using Google API directly
        # Construct backend callback URL to match environment
        backend_callback_url = request.build_absolute_uri('/api/auth/google/callback/')

        sys.stderr.write(f"Backend callback URL for token exchange: {backend_callback_url}\n")
        sys.stderr.flush()

        token_url = 'https://oauth2.googleapis.com/token'
        token_data = {
            'client_id': app.client_id,
            'client_secret': app.secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': backend_callback_url
        }

        sys.stderr.write(f"Sending token request to Google...\n")
        sys.stderr.flush()

        token_response = requests.post(token_url, data=token_data)

        sys.stderr.write(f"Token exchange status: {token_response.status_code}\n")
        sys.stderr.write(f"Token response: {token_response.text}\n")
        sys.stderr.flush()

        if token_response.status_code != 200:
            return Response({
                'error': 'Failed to exchange code for token',
                'details': token_response.text
            }, status=status.HTTP_400_BAD_REQUEST)
        
        token_info = token_response.json()
        access_token = token_info.get('access_token')
        
        # Step 4: Get user info from Google
        user_info_url = 'https://www.googleapis.com/oauth2/v2/userinfo'
        headers = {'Authorization': f'Bearer {access_token}'}
        user_response = requests.get(user_info_url, headers=headers)
        
        if user_response.status_code != 200:
            return Response({'error': 'Failed to get user info from Google'}, status=status.HTTP_400_BAD_REQUEST)
        
        user_data = user_response.json()
        print(f"DEBUG: User data from Google: {user_data}")

        # Step 5: Hybrid approval system - Check ApprovedEmail OR create registration request
        User = get_user_model()
        from billing.models import ApprovedEmail, UserRegistrationRequest

        user_email = user_data.get('email')
        user = None

        try:
            # Try to get existing user
            user = User.objects.get(email=user_email)
            print(f"DEBUG: Existing user found: {user.email}")
        except User.DoesNotExist:
            # User doesn't exist - check if email is pre-approved
            try:
                approved_email = ApprovedEmail.objects.get(email=user_email)
                # Email is pre-approved - create user with approved status
                user = User.objects.create(
                    email=user_email,
                    first_name=user_data.get('given_name', ''),
                    last_name=user_data.get('family_name', ''),
                    user_type=approved_email.user_type,
                    oauth_provider='google',
                    oauth_id=user_data.get('id'),
                    is_approved=True  # Pre-approved
                )
                print(f"DEBUG: User created from pre-approved email: {user.email}")
            except ApprovedEmail.DoesNotExist:
                # Not pre-approved - check for existing registration request
                try:
                    reg_request = UserRegistrationRequest.objects.get(email=user_email)
                    if reg_request.status == 'approved':
                        # Registration request was approved - create user
                        user = User.objects.create(
                            email=user_email,
                            first_name=user_data.get('given_name', ''),
                            last_name=user_data.get('family_name', ''),
                            user_type=reg_request.user_type,
                            oauth_provider='google',
                            oauth_id=user_data.get('id'),
                            is_approved=True
                        )
                        print(f"DEBUG: User created from approved registration: {user.email}")
                    elif reg_request.status == 'rejected':
                        error_url = f"{frontend_redirect_uri}?error=registration_rejected&message=Your registration request was rejected. Please contact support."
                        return HttpResponseRedirect(error_url)
                    else:  # pending
                        error_url = f"{frontend_redirect_uri}?error=approval_pending&message=Your registration is pending management approval. You will be able to login once approved."
                        return HttpResponseRedirect(error_url)
                except UserRegistrationRequest.DoesNotExist:
                    # No registration request - create one
                    UserRegistrationRequest.objects.create(
                        email=user_email,
                        first_name=user_data.get('given_name', ''),
                        last_name=user_data.get('family_name', ''),
                        user_type='teacher',  # Default
                        oauth_provider='google',
                        oauth_id=user_data.get('id'),
                        status='pending'
                    )
                    print(f"DEBUG: Registration request created for: {user_email}")
                    error_url = f"{frontend_redirect_uri}?error=approval_required&message=Thank you for registering! Your request is pending management approval. You will be able to login once approved."
                    return HttpResponseRedirect(error_url)
        except Exception as e:
            print(f"DEBUG: Error in approval flow: {str(e)}")
            return Response({'error': f'Approval flow error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Make sure we have a user object (could be None if registration request was created)
        if not user:
            error_url = f"{frontend_redirect_uri}?error=no_user&message=Unable to complete login. Please try again."
            return HttpResponseRedirect(error_url)

        # Step 7: Generate JWT tokens
        try:
            refresh = RefreshToken.for_user(user)
            print(f"DEBUG: JWT tokens generated successfully for user {user.email}")
        except Exception as e:
            print(f"DEBUG: JWT token generation failed: {str(e)}")
            return Response({'error': f'JWT token generation failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Get user name from Google data or use email as fallback
        user_name = f"{user.first_name} {user.last_name}".strip()
        if not user_name:
            user_name = user_data.get('name', user.email)  # Use Google's name or email

        # Prepare user data for URL encoding
        user_data_dict = {
            'email': user.email,
            'name': user_name,
            'user_id': user.id,
            'user_type': user.user_type,
            'is_approved': user.is_approved
        }

        # Build redirect URL with tokens and user data (using frontend_redirect_uri from state)
        params = {
            'access_token': str(refresh.access_token),
            'refresh_token': str(refresh),
            'user': urlencode(user_data_dict)
        }

        redirect_url = f"{frontend_redirect_uri}?{urlencode(params)}"

        # Redirect to frontend with tokens
        return HttpResponseRedirect(redirect_url)
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def oauth_success(request):
    """Handle successful OAuth login and redirect to frontend with JWT tokens"""
    try:
        # Check if user is authenticated (Django Allauth should have logged them in)
        if not request.user.is_authenticated:
            return HttpResponseRedirect('/login?error=not_authenticated')

        # Get frontend redirect URI from session
        default_frontend_redirect = f'{FRONTEND_URL}/oauth-callback'
        frontend_redirect_uri = request.session.get('frontend_redirect_uri', default_frontend_redirect)
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(request.user)
        
        # Get user name
        user_name = f"{request.user.first_name} {request.user.last_name}".strip()
        if not user_name:
            user_name = request.user.email
        
        # Prepare user data for URL encoding
        user_data = {
            'email': request.user.email,
            'name': user_name,
            'user_id': request.user.id,
            'user_type': getattr(request.user, 'user_type', 'teacher'),
            'is_approved': getattr(request.user, 'is_approved', False)
        }
        
        # Build redirect URL with tokens and user data
        params = {
            'access_token': str(refresh.access_token),
            'refresh_token': str(refresh),
            'user': urlencode(user_data)
        }
        
        redirect_url = f"{frontend_redirect_uri}?{urlencode(params)}"
        
        # Clear session data
        if 'frontend_redirect_uri' in request.session:
            del request.session['frontend_redirect_uri']
        
        # Redirect to frontend with tokens
        return HttpResponseRedirect(redirect_url)
        
    except Exception as e:
        return HttpResponseRedirect('/login?error=oauth_error')

 

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