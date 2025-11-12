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
def register_with_email(request):
    """
    Register new user with email/password and create registration request

    This endpoint creates a registration request for management approval.
    Similar to OAuth flow, but for email/password users.

    Expected request body:
    {
        "email": "user@example.com",
        "password": "userpassword",
        "first_name": "John",
        "last_name": "Doe",
        "user_type": "teacher"  # or "student"
    }

    Returns:
    {
        "message": "Registration request submitted. Pending management approval.",
        "email": "user@example.com"
    }
    """
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from billing.models import ApprovedEmail, UserRegistrationRequest

    User = get_user_model()

    # Get data from request
    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password')
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()
    user_type = request.data.get('user_type', 'teacher')  # Default to teacher

    # Validate required fields
    if not email or not password or not first_name or not last_name:
        return Response({
            'error': 'Email, password, first name, and last name are required'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Validate user_type
    valid_user_types = ['teacher', 'student']
    if user_type not in valid_user_types:
        return Response({
            'error': f'Invalid user type. Must be one of: {", ".join(valid_user_types)}'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Note: We do NOT check ALLOWED_EMAILS here for registration requests
    # Anyone should be able to submit a registration request
    # ALLOWED_EMAILS is only enforced at LOGIN time

    # Validate password strength
    try:
        validate_password(password)
    except ValidationError as e:
        return Response({
            'error': 'Password validation failed',
            'details': e.messages
        }, status=status.HTTP_400_BAD_REQUEST)

    # Check if user already exists
    if User.objects.filter(email=email).exists():
        return Response({
            'error': 'An account with this email already exists'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Check if email is pre-approved
    try:
        approved_email = ApprovedEmail.objects.get(email=email)
        # Email is pre-approved - create user directly with approved status
        user = User.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            user_type=approved_email.user_type,
            is_approved=True
        )

        # Generate JWT tokens for immediate login
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

    except ApprovedEmail.DoesNotExist:
        # Not pre-approved - check for existing registration request
        try:
            reg_request = UserRegistrationRequest.objects.get(email=email)

            if reg_request.status == 'approved':
                # Registration was approved - create user
                user = User.objects.create_user(
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    user_type=reg_request.user_type,
                    is_approved=True
                )

                # Generate JWT tokens for immediate login
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
            # No registration request exists - create one with hashed password
            # Store password temporarily so user can login after approval
            temp_user = User(email=email)
            temp_user.set_password(password)
            hashed_password = temp_user.password

            reg_request = UserRegistrationRequest.objects.create(
                email=email,
                first_name=first_name,
                last_name=last_name,
                user_type=user_type,
                status='pending'
            )
            # Store hashed password in notes field temporarily (not ideal but works)
            reg_request.notes = f"HASHED_PASSWORD:{hashed_password}"
            reg_request.save()

            return Response({
                'message': 'Registration request submitted successfully',
                'details': 'Your request is pending management approval. You will be able to login once approved.',
                'email': email
            }, status=status.HTTP_202_ACCEPTED)


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
                # Registration was approved but user not created yet - create user now
                # Extract hashed password from notes field
                if reg_request.notes and reg_request.notes.startswith('HASHED_PASSWORD:'):
                    # Extract just the hashed password (might have management notes appended)
                    notes_lines = reg_request.notes.split('\n')
                    password_line = notes_lines[0]  # First line has the password
                    hashed_password = password_line.replace('HASHED_PASSWORD:', '', 1).strip()

                    user = User.objects.create(
                        email=email,
                        first_name=reg_request.first_name,
                        last_name=reg_request.last_name,
                        user_type=reg_request.user_type,
                        is_approved=True
                    )
                    user.password = hashed_password
                    user.save()

                    # Try to authenticate again
                    user = authenticate(request, username=email, password=password)

                    if user is None:
                        return Response({
                            'error': 'Invalid email or password',
                            'message': 'Authentication failed after account creation. Please try registering again.'
                        }, status=status.HTTP_401_UNAUTHORIZED)
                else:
                    return Response({
                        'error': 'Account setup incomplete',
                        'message': f'Your registration was approved but password data is missing. Please contact support. (Notes: {reg_request.notes[:50] if reg_request.notes else "None"})'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_request(request):
    """
    Request password reset endpoint

    Sends a password reset email with a secure token to the user's email address.
    Only sends email if user exists and email is in the allowed emails list.

    Expected request body:
    {
        "email": "user@example.com"
    }

    Returns:
    {
        "message": "If an account exists with this email, you will receive a password reset link."
    }
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes

    email = request.data.get('email', '').strip().lower()

    if not email:
        return Response({
            'error': 'Email is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    User = get_user_model()

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        # Don't reveal if user exists or not for security
        return Response({
            'message': 'If an account exists with this email, you will receive a password reset link.'
        })

    # Generate password reset token
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    # Build reset link
    reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"

    # Send email
    subject = 'Password Reset - Maple Key Music Academy'
    message = f"""
Hello {user.first_name or user.email},

You requested to reset your password for your Maple Key Music Academy account.

Click the link below to reset your password:
{reset_url}

This link will expire in 1 hour.

If you did not request a password reset, please ignore this email.

Best regards,
Maple Key Music Academy Team
    """

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        print(f"DEBUG: Password reset email sent to {email}")
    except Exception as e:
        print(f"ERROR: Failed to send password reset email: {str(e)}")
        return Response({
            'error': 'Failed to send password reset email. Please try again later.'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'message': 'If an account exists with this email, you will receive a password reset link.'
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_validate_token(request):
    """
    Validate password reset token endpoint

    Checks if a password reset token is valid before showing the reset form.

    Expected request body:
    {
        "uid": "MQ",
        "token": "abc123-def456"
    }

    Returns:
    {
        "valid": true,
        "email": "user@example.com"
    }
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_decode
    from django.utils.encoding import force_str

    uid = request.data.get('uid')
    token = request.data.get('token')

    if not uid or not token:
        return Response({
            'error': 'Missing uid or token'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Decode user ID
        user_id = force_str(urlsafe_base64_decode(uid))
        User = get_user_model()
        user = User.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return Response({
            'error': 'Invalid or expired reset link',
            'valid': False
        }, status=status.HTTP_400_BAD_REQUEST)

    # Validate token
    if not default_token_generator.check_token(user, token):
        return Response({
            'error': 'Invalid or expired reset link',
            'valid': False
        }, status=status.HTTP_400_BAD_REQUEST)

    return Response({
        'valid': True,
        'email': user.email
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_confirm(request):
    """
    Confirm password reset endpoint

    Resets the user's password using the token and new password.

    Expected request body:
    {
        "uid": "MQ",
        "token": "abc123-def456",
        "password": "newpassword123",
        "confirm_password": "newpassword123"
    }

    Returns:
    {
        "message": "Password reset successful. You can now login with your new password."
    }
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_decode
    from django.utils.encoding import force_str
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    uid = request.data.get('uid')
    token = request.data.get('token')
    password = request.data.get('password')
    confirm_password = request.data.get('confirm_password')

    if not all([uid, token, password, confirm_password]):
        return Response({
            'error': 'All fields are required'
        }, status=status.HTTP_400_BAD_REQUEST)

    if password != confirm_password:
        return Response({
            'error': 'Passwords do not match'
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Decode user ID
        user_id = force_str(urlsafe_base64_decode(uid))
        User = get_user_model()
        user = User.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return Response({
            'error': 'Invalid or expired reset link'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Validate token
    if not default_token_generator.check_token(user, token):
        return Response({
            'error': 'Invalid or expired reset link'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Validate password strength
    try:
        validate_password(password, user)
    except ValidationError as e:
        return Response({
            'error': 'Password validation failed',
            'details': e.messages
        }, status=status.HTTP_400_BAD_REQUEST)

    # Set new password
    user.set_password(password)
    user.save()

    print(f"DEBUG: Password reset successful for user {user.email}")

    return Response({
        'message': 'Password reset successful. You can now login with your new password.'
    })