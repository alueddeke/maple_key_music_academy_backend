from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
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

    # User find-or-create + approval workflow
    # Ported from google_oauth_callback (debug prints removed)
    User = get_user_model()
    from billing.models import ApprovedEmail, UserRegistrationRequest, School
    user = None

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




@api_view(['POST'])
@permission_classes([AllowAny])
def register_with_email(request):
    """
    Register new user and create registration request for management approval

    This endpoint creates a registration request. No password required -
    users will set password via invitation email after approval.

    Expected request body:
    {
        "email": "user@example.com",
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
    from billing.models import ApprovedEmail, UserRegistrationRequest

    User = get_user_model()

    # Get data from request
    email = request.data.get('email', '').strip().lower()
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()
    user_type = request.data.get('user_type', 'teacher')  # Default to teacher

    # Validate required fields
    if not email or not first_name or not last_name:
        return Response({
            'error': 'Email, first name, and last name are required'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Validate user_type
    valid_user_types = ['teacher', 'student']
    if user_type not in valid_user_types:
        return Response({
            'error': f'Invalid user type. Must be one of: {", ".join(valid_user_types)}'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Check if user already exists
    if User.objects.filter(email=email).exists():
        return Response({
            'error': 'An account with this email already exists'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Check if email is pre-approved
    try:
        approved_email = ApprovedEmail.objects.get(email=email)
        # Email is pre-approved - they already have an invitation
        return Response({
            'error': 'Email already pre-approved',
            'message': 'This email is already pre-approved. Please check your email for the invitation link to set up your account.'
        }, status=status.HTTP_400_BAD_REQUEST)

    except ApprovedEmail.DoesNotExist:
        # Not pre-approved - check for existing registration request
        try:
            reg_request = UserRegistrationRequest.objects.get(email=email)

            if reg_request.status == 'approved':
                return Response({
                    'error': 'Registration already approved',
                    'message': 'Your registration was approved. Please check your email for the invitation link to set up your account.'
                }, status=status.HTTP_400_BAD_REQUEST)

            elif reg_request.status == 'rejected':
                return Response({
                    'error': 'Registration rejected',
                    'message': 'Your registration request was rejected. Please contact support.'
                }, status=status.HTTP_403_FORBIDDEN)
            else:  # pending
                return Response({
                    'error': 'Registration already submitted',
                    'message': 'Your registration is pending management approval. Please wait for approval.'
                }, status=status.HTTP_400_BAD_REQUEST)

        except UserRegistrationRequest.DoesNotExist:
            # No registration request exists - create one (no password needed)
            reg_request = UserRegistrationRequest.objects.create(
                email=email,
                first_name=first_name,
                last_name=last_name,
                user_type=user_type,
                status='pending'
            )

            return Response({
                'message': 'Registration request submitted successfully',
                'details': 'Your request is pending management approval. You will receive an invitation email once approved.',
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

                    school = getattr(getattr(reg_request, 'reviewed_by', None), 'school', None)
                    if school is None:
                        logger.error('Cannot derive school for reg_request user creation: %s', email)
                        return Response(
                            {'error': 'Server configuration error'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        )
                    user = User.objects.create(
                        email=email,
                        first_name=reg_request.first_name,
                        last_name=reg_request.last_name,
                        user_type=reg_request.user_type,
                        is_approved=True,
                        school=school
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
                        'message': 'Your registration was approved but account setup is incomplete. Please contact support.'
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
        logger.info('Password reset email sent to %s', email)
    except Exception as e:
        logger.error('Failed to send password reset email to %s: %s', email, str(e))
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

    User = get_user_model()
    try:
        # Decode user ID
        user_id = force_str(urlsafe_base64_decode(uid))
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

    User = get_user_model()
    try:
        # Decode user ID
        user_id = force_str(urlsafe_base64_decode(uid))
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

    logger.info('Password reset successful for user %s', user.email)

    return Response({
        'message': 'Password reset successful. You can now login with your new password.'
    })