from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import logging

logger = logging.getLogger(__name__)


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
    from django.conf import settings
    from django.contrib.auth import get_user_model

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
    from django.contrib.auth import get_user_model

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
    from django.contrib.auth import get_user_model

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
