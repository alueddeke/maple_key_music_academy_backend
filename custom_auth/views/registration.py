from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.contrib.auth import get_user_model
import logging

logger = logging.getLogger(__name__)


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
    from billing.models import ApprovedEmail, UserRegistrationRequest, School

    User = get_user_model()

    # Get data from request
    email = request.data.get('email', '').strip().lower()
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()
    user_type = request.data.get('user_type', 'teacher')  # Default to teacher
    school_id = request.data.get('school_id')

    school = None
    if school_id:
        try:
            school = School.objects.get(pk=school_id)
        except School.DoesNotExist:
            return Response({'error': 'Invalid school'}, status=status.HTTP_400_BAD_REQUEST)

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
                status='pending',
                school=school,
            )

            return Response({
                'message': 'Registration request submitted successfully',
                'details': 'Your request is pending management approval. You will receive an invitation email once approved.',
                'email': email
            }, status=status.HTTP_202_ACCEPTED)
