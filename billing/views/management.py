from django.shortcuts import render
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.utils import timezone
from ..models import Invoice, Lesson, BillableContact, MonthlyInvoiceBatch, BatchLessonItem, StudentInvoice, RecurringLessonsSchedule
from ..serializers import (
    UserSerializer, LessonSerializer, InvoiceSerializer, DetailedInvoiceSerializer,
    BillableContactSerializer, StudentCreateSerializer,
    MonthlyInvoiceBatchSerializer, BatchLessonItemSerializer, RecurringScheduleSerializer
)
from custom_auth.decorators import (
    role_required, teacher_required, management_required,
    teacher_or_management_required, owns_resource_or_management
)
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


# HELPER FUNCTIONS

def validate_batch_billable_contacts(batch):
    """
    Validate that all students in the batch have complete billable contact information.

    Returns:
        List of error dicts if validation fails, None if all valid.
        Each error dict: {
            'student_id': int,
            'student_name': str,
            'missing_fields': list of str
        }
    """
    errors = []

    # Get unique students from batch lesson items
    students = set(item.student for item in batch.lesson_items.all())

    required_fields = [
        'first_name', 'last_name', 'email', 'phone',
        'street_address', 'city', 'province', 'postal_code'
    ]

    for student in students:
        # Get primary billable contact
        try:
            primary_contact = student.billable_contacts.get(is_primary=True)
        except BillableContact.DoesNotExist:
            errors.append({
                'student_id': student.id,
                'student_name': student.get_full_name(),
                'missing_fields': ['primary_billable_contact'],
                'message': f'{student.get_full_name()} has no primary billable contact'
            })
            continue

        # Check for missing/empty required fields
        missing_fields = []
        for field in required_fields:
            value = getattr(primary_contact, field, None)
            if not value or (isinstance(value, str) and not value.strip()):
                missing_fields.append(field)

        if missing_fields:
            errors.append({
                'student_id': student.id,
                'student_name': student.get_full_name(),
                'missing_fields': missing_fields,
                'message': f'{student.get_full_name()} is missing: {", ".join(missing_fields)}'
            })

    return errors if errors else None


# USER MANAGEMENT ENDPOINTS

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def teacher_list(request):
    """Authenticated teacher directory + management teacher creation"""
    if request.method == 'GET':
        # Public endpoint - show approved teachers only
        # For authenticated users, filter by school; for public, show all (future: subdomain filtering)
        teachers = User.objects.filter(user_type='teacher', is_approved=True)
        if request.user.is_authenticated and hasattr(request.user, 'school') and request.user.school:
            teachers = teachers.filter(school=request.user.school)
        serializer = UserSerializer(teachers, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        # Only management can create teachers via API
        if not request.user.is_authenticated or request.user.user_type != 'management':
            return Response({
                'error': 'Management access required to create teacher accounts'
            }, status=status.HTTP_403_FORBIDDEN)

        data = request.data.copy()
        data['user_type'] = 'teacher'
        data['is_approved'] = True  # Management-created teachers are auto-approved

        serializer = UserSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@management_required
def all_teachers(request):
    """Management endpoint to see all teachers (approved and pending)"""
    teachers = User.objects.filter(user_type='teacher', school=request.user.school)
    serializer = UserSerializer(teachers, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@management_required
def approve_teacher(request, teacher_id):
    """Management endpoint to approve pending teachers"""
    try:
        teacher = User.objects.get(id=teacher_id, user_type='teacher', school=request.user.school)
        teacher.is_approved = True
        teacher.save()
        return Response({'message': 'Teacher approved successfully'})
    except User.DoesNotExist:
        return Response({'error': 'Teacher not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@role_required('student', 'management')
def student_list(request):
    """Students can see themselves, management can see all students"""
    if request.user.user_type == 'management':
        students = User.objects.filter(user_type='student', school=request.user.school)
    else:
        students = User.objects.filter(id=request.user.id)

    serializer = UserSerializer(students, many=True)
    return Response(serializer.data)


# MANAGEMENT ENDPOINTS FOR USER APPROVAL SYSTEM

@api_view(['GET', 'POST'])
@management_required
def approved_email_list(request):
    """Management can view and add pre-approved emails"""
    from ..models import ApprovedEmail
    from ..serializers import ApprovedEmailSerializer
    from ..invitation_utils import create_and_send_invitation

    if request.method == 'GET':
        approved_emails = ApprovedEmail.objects.filter(approved_by__school=request.user.school)
        serializer = ApprovedEmailSerializer(approved_emails, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        data = request.data.copy()
        data['approved_by'] = request.user.id
        serializer = ApprovedEmailSerializer(data=data)
        if serializer.is_valid():
            approved_email = serializer.save()

            # Create and send invitation
            success, message, invitation = create_and_send_invitation(approved_email)

            response_data = serializer.data
            response_data['invitation_sent'] = success
            response_data['invitation_message'] = message
            if invitation:
                response_data['invitation_token'] = invitation.token

            return Response(response_data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@management_required
def approved_email_delete(request, pk):
    """Management can delete pre-approved emails"""
    from ..models import ApprovedEmail

    try:
        approved_email = ApprovedEmail.objects.get(pk=pk, approved_by__school=request.user.school)
        approved_email.delete()
        return Response({'message': 'Approved email deleted successfully'}, status=status.HTTP_204_NO_CONTENT)
    except ApprovedEmail.DoesNotExist:
        return Response({'error': 'Approved email not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@management_required
def registration_request_list(request):
    """Management can view all registration requests scoped to their school"""
    from ..models import UserRegistrationRequest
    from ..serializers import UserRegistrationRequestSerializer

    requests = UserRegistrationRequest.objects.filter(school=request.user.school)
    status_filter = request.GET.get('status')
    if status_filter:
        requests = requests.filter(status=status_filter)

    serializer = UserRegistrationRequestSerializer(requests, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@management_required
def approve_registration_request(request, pk):
    """Management approves a registration request and sends invitation email"""
    from ..models import UserRegistrationRequest, ApprovedEmail, InvitationToken
    from ..invitation_utils import generate_invitation_token, send_invitation_email

    try:
        reg_request = UserRegistrationRequest.objects.get(pk=pk)

        if reg_request.status != 'pending':
            return Response({
                'error': 'Only pending requests can be approved'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Mark as approved
        reg_request.status = 'approved'
        reg_request.reviewed_by = request.user
        reg_request.reviewed_at = timezone.now()

        # Store management notes
        management_notes = request.data.get('notes', '')
        if management_notes:
            reg_request.notes = management_notes

        reg_request.save()

        # Create ApprovedEmail entry
        approved_email, created = ApprovedEmail.objects.get_or_create(
            email=reg_request.email,
            defaults={
                'user_type': reg_request.user_type,
                'approved_by': request.user,
                'notes': f'Approved from registration request'
            }
        )

        # Generate invitation token and send email
        token = generate_invitation_token(approved_email)
        success, message = send_invitation_email(token)

        if not success:
            logger.warning('Failed to send invitation email to %s: %s', reg_request.email, message)

        return Response({
            'message': 'Registration approved and invitation email sent',
            'email': reg_request.email,
            'user_type': reg_request.user_type
        })

    except UserRegistrationRequest.DoesNotExist:
        return Response({'error': 'Registration request not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@management_required
def reject_registration_request(request, pk):
    """Management rejects a registration request"""
    from ..models import UserRegistrationRequest

    try:
        reg_request = UserRegistrationRequest.objects.get(pk=pk)

        if reg_request.status != 'pending':
            return Response({
                'error': 'Only pending requests can be rejected'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Mark as rejected
        reg_request.status = 'rejected'
        reg_request.reviewed_by = request.user
        reg_request.reviewed_at = timezone.now()
        reg_request.notes = request.data.get('notes', '')
        reg_request.save()

        return Response({
            'message': 'Registration request rejected',
            'email': reg_request.email
        })

    except UserRegistrationRequest.DoesNotExist:
        return Response({'error': 'Registration request not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@management_required
def management_all_users(request):
    """Management can view all users with detailed information"""
    from ..serializers import DetailedUserSerializer

    # Filter by user_type if provided
    user_type = request.GET.get('user_type')
    approval_status = request.GET.get('is_approved')

    users = User.objects.filter(school=request.user.school)

    if user_type:
        users = users.filter(user_type=user_type)
    if approval_status is not None:
        users = users.filter(is_approved=approval_status.lower() == 'true')

    serializer = DetailedUserSerializer(users, many=True)
    return Response(serializer.data)


@api_view(['DELETE'])
@management_required
def management_delete_user(request, pk):
    """Management can delete any user (except themselves)"""
    try:
        user = User.objects.get(pk=pk, school=request.user.school)

        # Prevent self-deletion
        if user.id == request.user.id:
            return Response({
                'error': 'Cannot delete your own account'
            }, status=status.HTTP_400_BAD_REQUEST)

        user_email = user.email
        user.delete()

        return Response({
            'message': f'Successfully deleted user {user_email}'
        }, status=status.HTTP_200_OK)

    except User.DoesNotExist:
        return Response({
            'error': 'User not found'
        }, status=status.HTTP_404_NOT_FOUND)


# MANAGEMENT ENDPOINTS FOR INVOICE MANAGEMENT

@api_view(['GET'])
@management_required
def management_all_invoices(request):
    """Management can view all invoices with detailed information"""
    from ..serializers import DetailedInvoiceSerializer

    # Filters
    invoice_type = request.GET.get('invoice_type')
    status_filter = request.GET.get('status')
    teacher_id = request.GET.get('teacher_id')

    invoices = Invoice.objects.filter(school=request.user.school).order_by('-created_at')  # Newest first

    if invoice_type:
        invoices = invoices.filter(invoice_type=invoice_type)
    if status_filter:
        invoices = invoices.filter(status=status_filter)
    if teacher_id:
        invoices = invoices.filter(teacher_id=teacher_id)

    serializer = DetailedInvoiceSerializer(invoices, many=True)
    return Response(serializer.data)


@api_view(['PUT'])
@management_required
def management_update_invoice(request, pk):
    """Management can update invoice details"""
    from ..serializers import DetailedInvoiceSerializer

    try:
        invoice = Invoice.objects.get(pk=pk, school=request.user.school)

        if not invoice.can_be_edited():
            return Response({
                'error': 'This invoice cannot be edited',
                'message': f'Invoices with status "{invoice.status}" cannot be edited'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Track edit
        data = request.data.copy()
        invoice.last_edited_by = request.user
        invoice.last_edited_at = timezone.now()

        serializer = DetailedInvoiceSerializer(invoice, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['PUT'])
@management_required
def management_update_invoice_status(request, pk):
    """Management can update invoice status"""
    try:
        invoice = Invoice.objects.get(pk=pk, school=request.user.school)
        new_status = request.data.get('status')

        if new_status not in dict(Invoice.STATUS_CHOICES):
            return Response({
                'error': 'Invalid status'
            }, status=status.HTTP_400_BAD_REQUEST)

        invoice.status = new_status
        invoice.last_edited_by = request.user
        invoice.last_edited_at = timezone.now()

        # If approving, set approval fields
        if new_status == 'approved':
            invoice.approved_by = request.user
            invoice.approved_at = timezone.now()

        invoice.save()

        return Response({
            'message': 'Invoice status updated',
            'status': invoice.status
        })

    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@management_required
def management_recalculate_invoice(request, pk):
    """Management can recalculate invoice totals"""
    try:
        invoice = Invoice.objects.get(pk=pk, school=request.user.school)

        if not invoice.can_be_edited():
            return Response({
                'error': 'This invoice cannot be recalculated',
                'message': f'Invoices with status "{invoice.status}" cannot be edited'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Recalculate
        old_balance = invoice.payment_balance
        invoice.payment_balance = invoice.calculate_payment_balance()
        invoice.last_edited_by = request.user
        invoice.last_edited_at = timezone.now()
        invoice.save()

        return Response({
            'message': 'Invoice recalculated',
            'old_balance': old_balance,
            'new_balance': invoice.payment_balance
        })

    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@management_required
def management_reject_invoice(request, pk):
    """Management can reject an invoice with a reason"""
    try:
        invoice = Invoice.objects.get(pk=pk, school=request.user.school)
        rejection_reason = request.data.get('rejection_reason', '').strip()

        if not rejection_reason:
            return Response({
                'error': 'Rejection reason is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        if invoice.status not in ['pending', 'draft']:
            return Response({
                'error': 'Only pending or draft invoices can be rejected',
                'current_status': invoice.status
            }, status=status.HTTP_400_BAD_REQUEST)

        # Update invoice with rejection details
        invoice.status = 'rejected'
        invoice.rejected_by = request.user
        invoice.rejected_at = timezone.now()
        invoice.rejection_reason = rejection_reason
        invoice.save()

        logger.info(f"Invoice {invoice.invoice_number} rejected by {request.user.email}")

        return Response({
            'message': 'Invoice rejected successfully',
            'rejection_reason': rejection_reason,
            'rejected_at': invoice.rejected_at
        })

    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)


# SYSTEM SETTINGS ENDPOINTS

@api_view(['GET'])
@management_required
def get_system_settings(request):
    """Get system settings (management only)"""
    from ..models import SystemSettings
    from ..serializers import SystemSettingsSerializer

    settings = SystemSettings.get_settings()
    serializer = SystemSettingsSerializer(settings)
    return Response(serializer.data)


@api_view(['PUT'])
@management_required
def update_system_settings(request):
    """Update system settings (management only)"""
    from ..models import SystemSettings
    from ..serializers import SystemSettingsSerializer

    settings = SystemSettings.get_settings()
    serializer = SystemSettingsSerializer(settings, data=request.data, partial=True)

    if serializer.is_valid():
        # Set the updated_by field to the current user
        serializer.save(updated_by=request.user)
        return Response(serializer.data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@management_required
def list_invoice_recipients(request):
    """List all invoice recipient emails (management only)"""
    from ..models import InvoiceRecipientEmail
    from ..serializers import InvoiceRecipientEmailSerializer

    recipients = InvoiceRecipientEmail.objects.all()
    serializer = InvoiceRecipientEmailSerializer(recipients, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@management_required
def add_invoice_recipient(request):
    """Add a new invoice recipient email (management only)"""
    from ..models import InvoiceRecipientEmail
    from ..serializers import InvoiceRecipientEmailSerializer

    serializer = InvoiceRecipientEmailSerializer(data=request.data)

    if serializer.is_valid():
        # Check if email already exists
        email = serializer.validated_data['email']
        if InvoiceRecipientEmail.objects.filter(email=email).exists():
            return Response(
                {'error': 'This email is already in the recipient list'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Set created_by to current user
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@management_required
def delete_invoice_recipient(request, pk):
    """Delete an invoice recipient email (management only)"""
    from ..models import InvoiceRecipientEmail

    try:
        recipient = InvoiceRecipientEmail.objects.get(pk=pk)
        recipient.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    except InvoiceRecipientEmail.DoesNotExist:
        return Response(
            {'error': 'Recipient not found'},
            status=status.HTTP_404_NOT_FOUND
        )


# Step 2: Dual-Rate System API Endpoints

@api_view(['GET', 'PATCH'])
@management_required
def school_settings(request):
    """
    Get or update school settings for the user's school.
    Management only.
    """
    from ..models import SchoolSettings
    from ..serializers import SchoolSettingsSerializer

    # Get or create the school settings for user's school
    settings = SchoolSettings.get_settings_for_school(request.user.school)

    if request.method == 'GET':
        serializer = SchoolSettingsSerializer(settings)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = SchoolSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(updated_by=request.user)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@management_required
def teacher_list_with_stats(request):
    """
    List all teachers with computed stats.
    Management only.
    """
    from ..serializers import TeacherListSerializer

    teachers = User.objects.filter(
        user_type='teacher',
        is_approved=True,
        school=request.user.school
    ).order_by('last_name', 'first_name')
    serializer = TeacherListSerializer(teachers, many=True)
    return Response(serializer.data)


@api_view(['GET', 'PATCH'])
@management_required
def teacher_detail(request, pk):
    """
    Get teacher details with stats, or update teacher hourly_rate.
    Management only.
    """
    from ..serializers import TeacherDetailSerializer

    try:
        teacher = User.objects.get(pk=pk, user_type='teacher', school=request.user.school)
    except User.DoesNotExist:
        return Response({'error': 'Teacher not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = TeacherDetailSerializer(teacher)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        # Only allow updating hourly_rate
        if 'hourly_rate' not in request.data:
            return Response(
                {'error': 'Only hourly_rate can be updated'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate hourly_rate
        from decimal import Decimal, InvalidOperation
        try:
            new_rate = Decimal(str(request.data['hourly_rate']))
            if new_rate < 0:
                return Response(
                    {'error': 'Hourly rate must be positive'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (InvalidOperation, ValueError):
            return Response(
                {'error': 'Invalid hourly rate format'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update teacher hourly_rate
        teacher.hourly_rate = new_rate
        teacher.save()

        schedules_updated = 0
        if request.data.get('apply_to_schedules'):
            # Update active in-person recurring schedules
            schedules_updated = RecurringLessonsSchedule.objects.filter(
                teacher=teacher,
                is_active=True,
                lesson_type='in_person'
            ).update(teacher_rate=new_rate)

            # Update lesson items in open (draft/submitted) batches
            BatchLessonItem.objects.filter(
                batch__teacher=teacher,
                batch__status__in=['draft', 'submitted'],
                lesson_type='in_person'
            ).update(teacher_rate=new_rate)

        serializer = TeacherDetailSerializer(teacher)
        response_data = serializer.data
        response_data['schedules_updated'] = schedules_updated
        return Response(response_data)

# ============================================================================
# STUDENT MANAGEMENT ENDPOINTS
# ============================================================================

@api_view(['GET', 'POST'])
@management_required
def management_students(request):
    """List all students or create new student with billing contact"""
    if request.method == 'GET':
        # Get all active students
        include_inactive = request.GET.get('include_inactive', 'false').lower() == 'true'

        if include_inactive:
            students = User.objects.filter(user_type='student', school=request.user.school)
        else:
            students = User.objects.filter(user_type='student', is_active=True, school=request.user.school)

        serializer = UserSerializer(students, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        # Create student with billing contact
        serializer = StudentCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            student = serializer.save()
            return Response(
                UserSerializer(student).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@management_required
def management_student_detail(request, pk):
    """Get, update, or soft-delete a student"""
    try:
        student = User.objects.get(pk=pk, user_type='student', school=request.user.school)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = UserSerializer(student)
        return Response(serializer.data)

    elif request.method == 'PUT':
        # Update student information
        serializer = UserSerializer(student, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        # Soft delete - check for lessons/invoices first
        has_lessons = Lesson.objects.filter(student=student).exists()
        has_invoices = Invoice.objects.filter(student=student).exists()

        warning_message = None
        if has_lessons or has_invoices:
            lesson_count = Lesson.objects.filter(student=student).count()
            invoice_count = Invoice.objects.filter(student=student).count()
            warning_message = (
                f"Warning: This student has {lesson_count} lessons "
                f"and {invoice_count} invoices. "
                "Historical data will be preserved."
            )

        # Perform soft delete
        student.is_active = False
        student.save()

        return Response({
            'message': 'Student deleted successfully',
            'warning': warning_message
        }, status=status.HTTP_200_OK)


# ============================================================================
# BILLABLE CONTACT ENDPOINTS
# ============================================================================

@api_view(['POST'])
@management_required
def add_billable_contact(request, student_id):
    """Add a new billing contact for a student"""
    try:
        student = User.objects.get(pk=student_id, user_type='student', is_active=True, school=request.user.school)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    data = request.data.copy()
    data['student'] = student.id
    data['school'] = student.school.id  # Set school from student

    serializer = BillableContactSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@management_required
def manage_billable_contact(request, pk):
    """Get, update, or delete a billing contact"""
    try:
        contact = BillableContact.objects.get(pk=pk, school=request.user.school)
    except BillableContact.DoesNotExist:
        return Response({'error': 'Billing contact not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        # Get contact details for editing
        serializer = BillableContactSerializer(contact)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = BillableContactSerializer(contact, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        # Check if this is the last contact
        student = contact.student
        contact_count = BillableContact.objects.filter(student=student).count()

        if contact_count == 1:
            return Response({
                'error': 'Cannot delete the last billing contact for a student'
            }, status=status.HTTP_400_BAD_REQUEST)

        # If deleting primary, make another contact primary
        if contact.is_primary:
            other_contact = BillableContact.objects.filter(
                student=student
            ).exclude(pk=contact.pk).first()

            if other_contact:
                other_contact.is_primary = True
                other_contact.save()

        contact.delete()
        return Response({
            'message': 'Billing contact deleted successfully'
        }, status=status.HTTP_200_OK)


# ============================================================================
# RECURRING LESSON SCHEDULE ENDPOINTS
# ============================================================================

@api_view(['GET', 'POST'])
@management_required
def student_recurring_schedules(request, student_id):
    """List or create recurring schedules for a student"""
    try:
        student = User.objects.get(pk=student_id, user_type='student', is_active=True, school=request.user.school)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        # List all recurring schedules for this student
        schedules = RecurringLessonsSchedule.objects.filter(
            student=student,
            school=request.user.school
        ).order_by('day_of_week', 'start_time')

        serializer = RecurringScheduleSerializer(schedules, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        # Create new recurring schedule
        data = request.data.copy()
        data['student'] = student.id
        data['school'] = request.user.school.id

        # Validate teacher is assigned to student
        teacher_id = data.get('teacher')
        if teacher_id:
            if not student.assigned_teachers.filter(id=teacher_id).exists():
                return Response({
                    'error': 'Teacher must be assigned to student before creating schedule'
                }, status=status.HTTP_400_BAD_REQUEST)

        serializer = RecurringScheduleSerializer(data=data)
        if serializer.is_valid():
            serializer.save(created_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@management_required
def recurring_schedule_detail(request, student_id, schedule_id):
    """Get, update, or delete a specific recurring schedule"""
    try:
        student = User.objects.get(pk=student_id, user_type='student', is_active=True, school=request.user.school)
        schedule = RecurringLessonsSchedule.objects.get(
            pk=schedule_id,
            student=student,
            school=request.user.school
        )
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
    except RecurringLessonsSchedule.DoesNotExist:
        return Response({'error': 'Schedule not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = RecurringScheduleSerializer(schedule)
        return Response(serializer.data)

    elif request.method == 'PUT':
        # Validate teacher is still assigned if changing teacher
        teacher_id = request.data.get('teacher')
        if teacher_id and teacher_id != schedule.teacher.id:
            if not student.assigned_teachers.filter(id=teacher_id).exists():
                return Response({
                    'error': 'Teacher must be assigned to student'
                }, status=status.HTTP_400_BAD_REQUEST)

        serializer = RecurringScheduleSerializer(schedule, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        schedule.delete()
        return Response({
            'message': 'Recurring schedule deleted successfully'
        }, status=status.HTTP_200_OK)


# ============================================================================
# TEACHER-STUDENT ASSIGNMENT ENDPOINTS
# ============================================================================

@api_view(['POST'])
@management_required
def assign_teachers_to_student(request, student_id):
    """Assign one or more teachers to a student"""
    try:
        student = User.objects.get(pk=student_id, user_type='student', is_active=True, school=request.user.school)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    teacher_ids = request.data.get('teacher_ids', [])

    if not teacher_ids:
        return Response({'error': 'No teacher IDs provided'}, status=status.HTTP_400_BAD_REQUEST)

    # Validate teachers exist and are active
    teachers = User.objects.filter(
        id__in=teacher_ids,
        user_type='teacher',
        is_active=True
    )

    if teachers.count() != len(teacher_ids):
        return Response({
            'error': 'One or more teacher IDs are invalid or inactive'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Add teachers (keeps existing assignments)
    student.assigned_teachers.add(*teachers)

    return Response({
        'message': f'Assigned {teachers.count()} teacher(s) to {student.get_full_name()}',
        'assigned_teachers': [
            {'id': t.id, 'name': t.get_full_name()}
            for t in student.assigned_teachers.filter(is_active=True)
        ]
    })


@api_view(['DELETE'])
@management_required
def unassign_teacher_from_student(request, student_id, teacher_id):
    """Remove a teacher assignment from a student"""
    try:
        student = User.objects.get(pk=student_id, user_type='student', school=request.user.school)
        teacher = User.objects.get(pk=teacher_id, user_type='teacher', school=request.user.school)
    except User.DoesNotExist:
        return Response({'error': 'Student or teacher not found'}, status=status.HTTP_404_NOT_FOUND)

    student.assigned_teachers.remove(teacher)

    return Response({
        'message': f'Removed {teacher.get_full_name()} from {student.get_full_name()}'
    })


@api_view(['GET'])
@management_required
def teacher_students(request, teacher_id):
    """Get all students assigned to a teacher"""
    try:
        teacher = User.objects.get(pk=teacher_id, user_type='teacher', school=request.user.school)
    except User.DoesNotExist:
        return Response({'error': 'Teacher not found'}, status=status.HTTP_404_NOT_FOUND)

    # Get active students assigned to this teacher
    students = teacher.assigned_students.filter(is_active=True)
    serializer = UserSerializer(students, many=True)

    return Response({
        'teacher': {
            'id': teacher.id,
            'first_name': teacher.first_name,
            'last_name': teacher.last_name,
            'email': teacher.email,
            'instruments': teacher.instruments,
            'bio': teacher.bio
        },
        'students': serializer.data,
        'total_students': students.count()
    })


# ============================================================================
# TEACHER MANAGEMENT ENDPOINTS (UPDATE/DELETE ONLY, NO CREATE)
# ============================================================================

@api_view(['PUT'])
@management_required
def management_update_teacher(request, pk):
    """Update teacher information"""
    try:
        teacher = User.objects.get(pk=pk, user_type='teacher', school=request.user.school)
    except User.DoesNotExist:
        return Response({'error': 'Teacher not found'}, status=status.HTTP_404_NOT_FOUND)

    apply_to_schedules = request.data.get('apply_to_schedules', False)
    old_rate = teacher.hourly_rate

    serializer = UserSerializer(teacher, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()

        schedules_updated = 0
        rate_changed = 'hourly_rate' in request.data and teacher.hourly_rate != old_rate
        if apply_to_schedules and rate_changed:
            schedules_updated = RecurringLessonsSchedule.objects.filter(
                teacher=teacher,
                is_active=True,
                lesson_type='in_person'
            ).update(teacher_rate=teacher.hourly_rate)

            BatchLessonItem.objects.filter(
                batch__teacher=teacher,
                batch__status__in=['draft', 'submitted'],
                lesson_type='in_person'
            ).update(teacher_rate=teacher.hourly_rate)

        response_data = serializer.data
        response_data['schedules_updated'] = schedules_updated
        return Response(response_data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@management_required
def management_delete_teacher(request, pk):
    """Soft delete a teacher"""
    try:
        teacher = User.objects.get(pk=pk, user_type='teacher', school=request.user.school)
    except User.DoesNotExist:
        return Response({'error': 'Teacher not found'}, status=status.HTTP_404_NOT_FOUND)

    # Check for lessons/invoices
    has_lessons = Lesson.objects.filter(teacher=teacher).exists()
    has_invoices = Invoice.objects.filter(teacher=teacher).exists()

    warning_message = None
    if has_lessons or has_invoices:
        lesson_count = Lesson.objects.filter(teacher=teacher).count()
        invoice_count = Invoice.objects.filter(teacher=teacher).count()
        warning_message = (
            f"Warning: This teacher has {lesson_count} lessons "
            f"and {invoice_count} invoices. "
            "Historical data will be preserved."
        )

    # Perform soft delete
    teacher.is_active = False
    teacher.save()

    return Response({
        'message': 'Teacher deleted successfully',
        'warning': warning_message
    }, status=status.HTTP_200_OK)

# ============================================================================
# SCHOOL MANAGEMENT ENDPOINTS
# ============================================================================

@api_view(['GET'])
@management_required
def get_current_school(request):
    """Get current school details with stats (management only)"""
    from ..serializers import SchoolDetailSerializer

    school = request.user.school
    if not school:
        return Response({
            'error': 'No school assigned to user'
        }, status=status.HTTP_400_BAD_REQUEST)

    serializer = SchoolDetailSerializer(school)
    return Response(serializer.data)


@api_view(['PUT', 'PATCH'])
@management_required
def update_school(request):
    """Update current school information (management only)"""
    from ..serializers import SchoolSerializer

    school = request.user.school
    if not school:
        return Response({
            'error': 'No school assigned to user'
        }, status=status.HTTP_400_BAD_REQUEST)

    # Partial update allowed
    serializer = SchoolSerializer(school, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# ============================================================================
# MANAGEMENT APPROVAL WORKFLOW (Phase 4)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_pending_batches(request):
    """List all submitted batches waiting for approval"""
    batches = MonthlyInvoiceBatch.objects.filter(
        status='submitted',
        school=request.user.school
    ).order_by('submitted_at')

    serializer = MonthlyInvoiceBatchSerializer(batches, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_approved_batches(request):
    """List all approved batches"""
    batches = MonthlyInvoiceBatch.objects.filter(
        status='approved',
        school=request.user.school
    ).order_by('-reviewed_at')

    serializer = MonthlyInvoiceBatchSerializer(batches, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_rejected_batches(request):
    """List all rejected batches"""
    batches = MonthlyInvoiceBatch.objects.filter(
        status='draft',
        rejection_reason__isnull=False,  # Has rejection reason = was rejected
        school=request.user.school
    ).order_by('-reviewed_at')

    serializer = MonthlyInvoiceBatchSerializer(batches, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_batch_detail(request, batch_id):
    """
    Get batch detail with validation checks.
    Returns batch data plus validation errors if students have incomplete billable contacts.
    """
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    # Validate billable contacts for all students in this batch
    validation_errors = validate_batch_billable_contacts(batch)

    # Serialize batch data
    serializer = MonthlyInvoiceBatchSerializer(batch)
    response_data = serializer.data

    # Add validation errors if any
    if validation_errors:
        response_data['validation_errors'] = validation_errors
        response_data['can_approve'] = False
    else:
        response_data['can_approve'] = batch.status == 'submitted'

    return Response(response_data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
@management_required
def management_edit_lesson_notes(request, batch_id, item_id):
    """
    Edit teacher notes for a specific lesson item in a batch.
    Management can fix minor typos before approving.
    Only allowed for batches in 'submitted' status.
    """
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    if batch.status != 'submitted':
        return Response(
            {'error': 'Can only edit notes for batches in submitted status'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        lesson_item = batch.lesson_items.get(id=item_id)
    except BatchLessonItem.DoesNotExist:
        return Response({'error': 'Lesson item not found'}, status=status.HTTP_404_NOT_FOUND)

    # Only allow editing teacher_notes and cancellation_reason
    allowed_fields = ['teacher_notes', 'cancellation_reason']
    updated = False

    for field in allowed_fields:
        if field in request.data:
            setattr(lesson_item, field, request.data[field])
            updated = True

    if updated:
        lesson_item.save()

    serializer = BatchLessonItemSerializer(lesson_item)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_approve_batch(request, batch_id):
    """
    Approve batch and generate Helcim CSV (atomic operation).

    Steps:
    1. Validate all students have complete billable contact data
    2. Generate StudentInvoice records for each student (completed lessons only)
    3. Mark batch as approved
    4. Generate and return Helcim CSV file

    If any step fails, entire transaction is rolled back.
    """
    from django.db import transaction
    from ..models import StudentInvoice, SchoolSettings
    from ..services.helcim_csv_generator import generate_helcim_csv
    from collections import defaultdict

    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    if batch.status != 'submitted':
        return Response(
            {'error': 'Batch must be in submitted status'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # VALIDATION PHASE: Check billable contacts before starting transaction
    validation_errors = validate_batch_billable_contacts(batch)
    if validation_errors:
        return Response(
            {
                'error': 'Cannot approve batch - incomplete student data',
                'validation_errors': validation_errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get school settings for payment terms
    school_settings = SchoolSettings.get_settings_for_school(batch.school)

    try:
        with transaction.atomic():
            # Group completed lesson items by student (exclude cancelled)
            completed_items_by_student = defaultdict(list)

            for item in batch.lesson_items.filter(status='completed'):
                completed_items_by_student[item.student].append(item)

            if not completed_items_by_student:
                raise ValueError('No completed lessons in batch')

            # Create StudentInvoice for each student
            student_invoices = []

            for student, lesson_items in completed_items_by_student.items():
                # Get primary billable contact
                primary_contact = student.billable_contacts.get(is_primary=True)

                # Create student invoice
                student_invoice = StudentInvoice(
                    batch=batch,
                    student=student,
                    school=batch.school,
                    amount=0,  # Will be calculated after adding lesson items

                    # Cache billable contact data
                    billing_contact_name=f"{primary_contact.first_name} {primary_contact.last_name}",
                    billing_email=primary_contact.email,
                    billing_phone=primary_contact.phone,
                    billing_street_address=primary_contact.street_address,
                    billing_city=primary_contact.city,
                    billing_province=primary_contact.province,
                    billing_postal_code=primary_contact.postal_code,
                )
                student_invoice.save()  # Save to get ID for M2M relationship

                # Add lesson items to invoice
                student_invoice.lesson_items.set(lesson_items)

                # Calculate total amount
                student_invoice.amount = student_invoice.calculate_amount()
                student_invoice.save()

                student_invoices.append(student_invoice)

            # Mark batch as approved
            batch.status = 'approved'
            batch.reviewed_by = request.user
            batch.reviewed_at = timezone.now()
            batch.save()

            # Generate CSV (this returns HttpResponse)
            csv_response = generate_helcim_csv(student_invoices, school_settings)

            # Return CSV file directly
            return csv_response

    except Exception as e:
        # Transaction will auto-rollback on exception
        logger.error(f'Batch approval failed: {str(e)}')
        return Response(
            {'error': f'Approval failed: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_reject_batch(request, batch_id):
    """Reject batch with reason"""
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    if batch.status != 'submitted':
        return Response(
            {'error': 'Batch must be in submitted status'},
            status=status.HTTP_400_BAD_REQUEST
        )

    rejection_reason = request.data.get('rejection_reason', '')
    if not rejection_reason:
        return Response(
            {'error': 'rejection_reason is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Set batch back to draft so teacher can edit and resubmit
    batch.status = 'draft'
    batch.reviewed_by = request.user
    batch.reviewed_at = timezone.now()
    batch.rejection_reason = rejection_reason
    batch.save()

    # TODO: Send email notification to teacher (future phase)

    serializer = MonthlyInvoiceBatchSerializer(batch)
    return Response(serializer.data)
