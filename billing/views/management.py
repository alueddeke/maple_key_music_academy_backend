from django.shortcuts import render
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from ..models import Invoice, Lesson, BillableContact, MonthlyInvoiceBatch, BatchLessonItem, BatchRejectionSnapshot, StudentInvoice, RecurringLessonsSchedule, SchoolMonthlyExpenses, PreBillingInvoice, SchoolExpenseItem
from ..serializers import (
    UserSerializer, LessonSerializer, InvoiceSerializer, DetailedInvoiceSerializer,
    BillableContactSerializer, StudentCreateSerializer,
    MonthlyInvoiceBatchSerializer, BatchLessonItemSerializer, RecurringScheduleSerializer,
    BatchRejectionSnapshotSerializer
)
from custom_auth.decorators import (
    role_required, teacher_required, management_required,
    teacher_or_management_required, owns_resource_or_management
)
import logging
import calendar
from datetime import date
from decimal import Decimal

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
        reg_request = UserRegistrationRequest.objects.get(pk=pk, school=request.user.school)

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
        reg_request = UserRegistrationRequest.objects.get(pk=pk, school=request.user.school)

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


@api_view(['GET', 'PUT'])
@management_required
def waive_policy_settings(request):
    """School waived-cancellation policy (MAP-101). Management-only."""
    from ..models import SchoolSettings
    from ..serializers import WaivePolicySerializer

    settings = SchoolSettings.get_settings_for_school(request.user.school)

    if request.method == 'GET':
        return Response(WaivePolicySerializer(settings).data)

    serializer = WaivePolicySerializer(settings, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save(updated_by=request.user)
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@management_required
def list_invoice_recipients(request):
    """List all invoice recipient emails (management only)"""
    from ..models import InvoiceRecipientEmail
    from ..serializers import InvoiceRecipientEmailSerializer

    recipients = InvoiceRecipientEmail.objects.filter(school=request.user.school)
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
        # Check if email already exists for this school
        email = serializer.validated_data['email']
        if InvoiceRecipientEmail.objects.filter(email=email, school=request.user.school).exists():
            return Response(
                {'error': 'This email is already in the recipient list'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Set created_by to current user and scope to school
        serializer.save(created_by=request.user, school=request.user.school)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@management_required
def delete_invoice_recipient(request, pk):
    """Delete an invoice recipient email (management only)"""
    from ..models import InvoiceRecipientEmail

    try:
        recipient = InvoiceRecipientEmail.objects.get(pk=pk, school=request.user.school)
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
# STUDENT PAUSE/RESUME ENDPOINTS
# ============================================================================

def reconcile_open_batches_for_student(student, school):
    """
    Re-sync FUTURE-dated, schedule-sourced lesson items for ``student`` in this
    school's still-open (``draft``/``submitted``) teacher batches to match the
    live, pause-aware projection (``get_scheduled_lessons_data``).

    Called after a pause/resume change so teachers submit accurate invoices:
    - PAUSE: future items now inside the pause window are no longer projected,
      so they are DELETED from open batches.
    - RESUME: future items the schedule projects again (and are missing) are
      ADDED back to open batches.

    Boundaries (billing integrity):
    - Only ``draft`` and ``submitted`` batches are touched. ``approved`` batches
      are locked (Lesson records / invoices already exist) and never change
      (T-26-10).
    - Only items with ``scheduled_date > today`` are touched. Lessons that have
      already happened are billable and are never removed or resurrected.
    - Only schedule-sourced items (``recurring_schedule`` set) are deleted;
      manual one-offs are left alone.
    """
    today = date.today()
    teacher_ids = list(
        RecurringLessonsSchedule.objects.filter(
            student=student, school=school, is_active=True
        ).values_list('teacher_id', flat=True).distinct()
    )
    if not teacher_ids:
        return

    batches = MonthlyInvoiceBatch.objects.filter(
        school=school,
        status__in=['draft', 'submitted'],
        teacher_id__in=teacher_ids,
    )
    for batch in batches:
        projected = [
            d for d in batch.get_scheduled_lessons_data()
            if d['student'].id == student.id and d['scheduled_date'] > today
        ]
        projected_keys = {(d['scheduled_date'], d['start_time']) for d in projected}

        # DELETE future, schedule-sourced items the live projection no longer
        # includes (now inside the pause window).
        future_items = BatchLessonItem.objects.filter(
            batch=batch,
            student=student,
            scheduled_date__gt=today,
            recurring_schedule__isnull=False,
        )
        for item in future_items:
            if (item.scheduled_date, item.start_time) not in projected_keys:
                item.delete()

        # ADD future projected items missing from the batch (resume restores).
        present_keys = {
            (i.scheduled_date, i.start_time)
            for i in BatchLessonItem.objects.filter(batch=batch, student=student)
        }
        for d in projected:
            if (d['scheduled_date'], d['start_time']) not in present_keys:
                BatchLessonItem.objects.create(
                    batch=batch,
                    student=student,
                    scheduled_date=d['scheduled_date'],
                    start_time=d['start_time'],
                    duration=d['duration'],
                    lesson_type=d['lesson_type'],
                    teacher_rate=d['teacher_rate'],
                    student_rate=d['student_rate'],
                    status=d['status'],
                    recurring_schedule=d['recurring_schedule'],
                    is_one_off=False,
                )


@api_view(['POST'])
@management_required
def student_pause_lessons(request, student_id):
    """
    Apply or clear a pause window across ALL of a student's recurring schedules.

    POST body:
      { "pause_start": "YYYY-MM-DD",  -- required for pause; null to clear
        "pause_end":   "YYYY-MM-DD" | null }

    Behaviour:
    - Both fields non-null  -> bounded pause (pause_end >= pause_start).
    - pause_start non-null, pause_end null -> open-ended pause.
    - Both null -> clear the window (Resume).

    School-scoped lookup: cross-school student_id returns 404 (IDOR-safe, T-26-02).
    Only management may call (T-26-01).
    """
    from datetime import datetime as _dt

    # Scope student lookup to the caller's school (IDOR guard T-26-02)
    try:
        student = User.objects.get(
            pk=student_id,
            user_type='student',
            is_active=True,
            school=request.user.school,
        )
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    body = request.data
    pause_start_raw = body.get('pause_start', '__missing__')
    pause_end_raw = body.get('pause_end', None)

    # pause_start is required in the body (key must be present)
    if pause_start_raw == '__missing__':
        return Response(
            {'error': 'pause_start is required (use null to clear the window)'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Parse dates (T-26-03)
    pause_start = None
    pause_end = None

    if pause_start_raw is not None:
        try:
            pause_start = _dt.strptime(str(pause_start_raw), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return Response(
                {'error': 'pause_start must be a valid date (YYYY-MM-DD) or null'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    if pause_end_raw is not None:
        try:
            pause_end = _dt.strptime(str(pause_end_raw), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return Response(
                {'error': 'pause_end must be a valid date (YYYY-MM-DD) or null'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Ordering validation: when both set, pause_end must be >= pause_start (T-26-03)
    if pause_start is not None and pause_end is not None and pause_end < pause_start:
        return Response(
            {'error': 'pause_end must be on or after pause_start'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Apply to all of the student's schedules in this school (D-02)
    RecurringLessonsSchedule.objects.filter(
        student=student,
        school=request.user.school,
    ).update(pause_start=pause_start, pause_end=pause_end)

    # Reflect the change on open teacher batches so teachers submit accurate
    # invoices: remove now-paused future lessons (and restore them on resume).
    reconcile_open_batches_for_student(student, request.user.school)

    # Return updated schedules serialized
    schedules = RecurringLessonsSchedule.objects.filter(
        student=student,
        school=request.user.school,
    )
    serializer = RecurringScheduleSerializer(schedules, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


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
        school=request.user.school,
        archived_at__isnull=True,
    ).order_by('-reviewed_at')

    serializer = MonthlyInvoiceBatchSerializer(batches, many=True)
    return Response(serializer.data)


# Phase 22: Month-End Adjustments
@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_month_end_queue(request):
    """
    ADJ-09: Approved batches without a teacher Invoice yet — the month-end work queue.
    Returns batches where status='approved' AND invoice FK is NULL, school-scoped.
    """
    batches = MonthlyInvoiceBatch.objects.filter(
        status='approved',
        invoice__isnull=True,
        school=request.user.school,
        archived_at__isnull=True,
    ).order_by('-reviewed_at')

    serializer = MonthlyInvoiceBatchSerializer(batches, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_generate_teacher_invoice(request, batch_id):
    """
    ADJ-05/06: Generate the teacher payment Invoice for an approved batch.

    Teacher pay covers every lesson the teacher actually delivered — see
    BatchLessonItem.calculate_teacher_payment() for the canonical per-lesson rule:
      - completed / confirmed: paid (past lessons display as "Completed" but keep DB
        status 'confirmed'; a normal submitted batch is entirely 'confirmed').
      - trial: paid at the teacher's normal rate. Trials are a business expense to
        win new clients — the teacher is paid, the student is charged $0.
      - forfeited: paid. Student no-show — the student is still charged, the teacher
        is still paid.
      - waived / cancelled: $0.

    Atomically:
      1. Creates Invoice(invoice_type='teacher_payment') with total_amount =
         Σ calculate_teacher_payment() over all BatchLessonItems.
      2. Links batch.invoice = invoice (signals batch lock for teacher adjustments, ADJ-07).
      3. Writes CreditTransaction(waived_rollover) per waived item (D-05 — deferred from
         approval): refunds the approval-time charge as next-month student credit.
      4. Writes CreditTransaction(forfeited) per forfeited item as the audit record for the
         no-show charge. The student's balance was already decremented at approval (the
         lesson counted as a 'confirmed' charge then), so balance is NOT touched here —
         this only records WHY the charge stands. Dedup-guarded so a lesson forfeited
         before approval (already carrying a 'forfeited' row) is not double-recorded.

    Returns 400 if batch not approved or Invoice already generated.
    Returns 404 if batch not in management's school (T-22-03 school isolation).
    """
    from collections import Counter
    from django.db import transaction as db_transaction
    from ..models import CreditTransaction, StudentCreditAccount

    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            school=request.user.school,
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    if batch.status != 'approved':
        return Response(
            {'error': 'Batch must be approved before generating teacher Invoice'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if batch.invoice_id is not None:
        return Response(
            {'error': 'Teacher Invoice already generated for this batch'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with db_transaction.atomic():
        # Teacher pay = Σ calculate_teacher_payment() over every item, so the invoice
        # total can never drift from the canonical per-lesson rule (pays completed,
        # confirmed, trial, forfeited; $0 for waived and cancelled). Summing the model
        # method instead of a hardcoded status filter is what fixes the historical
        # bug where an all-'confirmed' batch generated a $0 teacher invoice.
        all_items = list(batch.lesson_items.all())
        total_amount = sum(
            (item.calculate_teacher_payment() for item in all_items),
            Decimal('0.00'),
        )

        # Create Invoice with total_amount set at creation — do NOT call invoice.save()
        # afterward (Pitfall 7: Invoice.save() recalculates from M2M lessons which is empty).
        invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=batch.teacher,
            school=batch.school,
            status='pending',
            created_by=request.user,
            payment_balance=total_amount,
            total_amount=total_amount,
        )

        # Link batch to invoice — signals batch lock for teacher adjustment endpoint (ADJ-07)
        batch.invoice = invoice
        batch.save(update_fields=['invoice'])

        # D-05: Write waived_rollover CreditTransactions now (deferred from batch approval)
        waived_items = list(batch.lesson_items.filter(status='waived'))
        for item in waived_items:
            lesson_rate = item.student_rate * item.duration
            if lesson_rate > Decimal('0.00'):
                # get_or_create then re-acquire with select_for_update (REC-02 pattern)
                StudentCreditAccount.objects.get_or_create(
                    student=item.student,
                    school=batch.school,
                    defaults={'balance': Decimal('0.00')},
                )
                account = StudentCreditAccount.objects.select_for_update().get(
                    student=item.student, school=batch.school
                )
                account.balance += lesson_rate
                account.save()
                CreditTransaction.objects.create(
                    account=account,
                    school=batch.school,
                    type='waived_rollover',
                    amount=lesson_rate,
                )

        # Forfeited audit rows (ADJ/REC-04). The student was already charged at
        # approval (the lesson counted as a 'confirmed' decrement then), so we do NOT
        # touch balance here — we only write the CreditTransaction(type='forfeited')
        # that records the no-show. Grouped by (student, charge) and dedup-guarded
        # against any 'forfeited' row already written at approval, so a lesson that
        # was forfeited before approval is never double-recorded.
        forfeited_charges = Counter()
        for item in batch.lesson_items.filter(status='forfeited'):
            charge = item.student_rate * item.duration
            if charge > Decimal('0.00'):
                forfeited_charges[(item.student_id, charge)] += 1

        forfeited_credits_written = 0
        for (student_id, charge), needed in forfeited_charges.items():
            StudentCreditAccount.objects.get_or_create(
                student_id=student_id,
                school=batch.school,
                defaults={'balance': Decimal('0.00')},
            )
            account = StudentCreditAccount.objects.select_for_update().get(
                student_id=student_id, school=batch.school
            )
            existing = CreditTransaction.objects.filter(
                account=account, type='forfeited', amount=charge
            ).count()
            for _ in range(max(0, needed - existing)):
                CreditTransaction.objects.create(
                    account=account,
                    school=batch.school,
                    type='forfeited',
                    amount=charge,
                )
                forfeited_credits_written += 1

    return Response({
        'status': 'invoice_generated',
        'invoice_id': invoice.id,
        'invoice_number': invoice.invoice_number,
        'total_amount': str(invoice.total_amount),
        'waived_credits_written': len(waived_items),
        'forfeited_credits_written': forfeited_credits_written,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_rejected_batches(request):
    """List all rejected batches.

    A rejected batch is a draft that carries a rejection_reason. rejection_reason is
    a TextField (blank=True) that defaults to '' — never NULL — so filtering on
    isnull alone matches every fresh draft. Exclude the empty string so only
    genuinely-rejected batches appear (and stay deletable; the delete guard uses the
    same rule).
    """
    batches = MonthlyInvoiceBatch.objects.filter(
        status='draft',
        school=request.user.school,
        archived_at__isnull=True,
    ).exclude(rejection_reason='').exclude(rejection_reason__isnull=True).order_by('-reviewed_at')

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

    allowed_fields = [
        'teacher_notes', 'cancellation_reason', 'status',
        'scheduled_date', 'start_time', 'duration', 'lesson_type', 'admin_notes',
    ]

    if 'status' in request.data:
        allowed_statuses = ['trial', 'completed', 'confirmed', 'cancelled', 'forfeited', 'waived']
        if request.data['status'] not in allowed_statuses:
            return Response(
                {'error': f"Invalid status. Allowed values: {', '.join(allowed_statuses)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

    update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
    serializer = BatchLessonItemSerializer(lesson_item, data=update_data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
    from ..models import StudentInvoice, SchoolSettings, StudentCreditAccount, CreditTransaction, PreBillingInvoice
    from collections import defaultdict
    import calendar
    from datetime import date as _date

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
            from decimal import Decimal

            # Group billable items by student (cancelled items skipped entirely).
            # 'confirmed' and 'completed' are both billable in the pre-billing model —
            # confirmed = scheduled/upcoming, completed = already happened; billing outcome identical.
            completed_items_by_student = defaultdict(list)
            trial_items = []

            for item in batch.lesson_items.filter(status__in=['completed', 'confirmed']):
                completed_items_by_student[item.student].append(item)

            for item in batch.lesson_items.filter(status='trial'):
                trial_items.append(item)

            # Phase 20: forfeited/waived items are also valid batch content
            forfeited_items_count = batch.lesson_items.filter(status='forfeited').count()
            waived_items_count = batch.lesson_items.filter(status='waived').count()
            if not completed_items_by_student and not trial_items and not forfeited_items_count and not waived_items_count:
                raise ValueError('No billable lessons in batch')

            # Create Lesson records for trial items (teacher paid, student not invoiced)
            for item in trial_items:
                Lesson.objects.create(
                    teacher=batch.teacher,
                    student=item.student,
                    school=batch.school,
                    lesson_type=item.lesson_type,
                    is_trial=True,
                    scheduled_date=item.scheduled_date,
                    duration=item.duration,
                    teacher_rate=item.teacher_rate,
                    student_rate=Decimal('0.00'),
                    status='trial',
                    completed_date=None,
                    teacher_notes=item.teacher_notes,
                )

            # Create StudentInvoice + Lesson.confirmed records for each student
            student_invoices = []

            for student, lesson_items in completed_items_by_student.items():
                # Get primary billable contact
                primary_contact = student.billable_contacts.get(is_primary=True)

                # Create Lesson.confirmed for each completed item (used by pre-billing
                # draft generation in Phase 19). Sets created_lesson FK on the item.
                #
                # Two-step create required: Lesson.save() auto-promotes to is_trial=True
                # when the student has no completed lessons — we bypass this by setting
                # _is_trial_explicitly_set before save() fires.
                for item in lesson_items:
                    lesson = Lesson(
                        teacher=batch.teacher,
                        student=item.student,
                        school=batch.school,
                        lesson_type=item.lesson_type,
                        is_trial=False,
                        scheduled_date=item.scheduled_date,
                        duration=item.duration,
                        teacher_rate=item.teacher_rate,
                        student_rate=item.student_rate,
                        status='confirmed',
                        teacher_notes=item.teacher_notes,
                    )
                    lesson._is_trial_explicitly_set = True  # bypass auto-trial detection
                    lesson.save()
                    item.created_lesson = lesson
                    item.save(update_fields=['created_lesson'])

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

            # Phase 20 (D-07): create Lesson records for forfeited/waived items
            # Reuses confirmed-lesson pattern: Lesson(), _is_trial_explicitly_set, .save()
            forfeited_items_by_student = defaultdict(list)
            for item in batch.lesson_items.filter(status='forfeited'):
                lesson = Lesson(
                    teacher=batch.teacher,
                    student=item.student,
                    school=batch.school,
                    lesson_type=item.lesson_type,
                    is_trial=False,
                    scheduled_date=item.scheduled_date,
                    duration=item.duration,
                    teacher_rate=item.teacher_rate,
                    student_rate=item.student_rate,
                    status='forfeited',
                    teacher_notes=item.teacher_notes,
                )
                lesson._is_trial_explicitly_set = True
                lesson.save()
                item.created_lesson = lesson
                item.save(update_fields=['created_lesson'])
                forfeited_items_by_student[item.student].append(item)

            waived_items_by_student = defaultdict(list)
            for item in batch.lesson_items.filter(status='waived'):
                lesson = Lesson(
                    teacher=batch.teacher,
                    student=item.student,
                    school=batch.school,
                    lesson_type=item.lesson_type,
                    is_trial=False,
                    scheduled_date=item.scheduled_date,
                    duration=item.duration,
                    teacher_rate=item.teacher_rate,
                    student_rate=item.student_rate,
                    status='waived',
                    teacher_notes=item.teacher_notes,
                )
                lesson._is_trial_explicitly_set = True
                lesson.save()
                item.created_lesson = lesson
                item.save(update_fields=['created_lesson'])
                waived_items_by_student[item.student].append(item)

            # Phase 20 (D-08): forfeited added to StudentInvoice M2M; waived excluded
            # CRITICAL: StudentInvoice.lesson_items M2M target is BatchLessonItem (NOT Lesson).
            # Pass BatchLessonItem instances via *f_items, NOT item.created_lesson.
            for student, f_items in forfeited_items_by_student.items():
                existing_invoice = next(
                    (inv for inv in student_invoices if inv.student == student), None
                )
                if existing_invoice:
                    existing_invoice.lesson_items.add(*f_items)
                    # Recalculate amount to include forfeited charges (Pitfall 5 guard)
                    existing_invoice.amount = existing_invoice.calculate_amount()
                    existing_invoice.save(update_fields=['amount'])
                else:
                    # Forfeited-only student: no completed-lesson invoice was created above.
                    # Create a StudentInvoice now so the subsequent credit deduction (D-09)
                    # has an invoice record — a deduction without an invoice is a financial
                    # inconsistency in the audit ledger.
                    primary_contact = student.billable_contacts.get(is_primary=True)
                    forfeited_invoice = StudentInvoice(
                        batch=batch,
                        student=student,
                        school=batch.school,
                        amount=Decimal('0.00'),
                        billing_contact_name=f"{primary_contact.first_name} {primary_contact.last_name}",
                        billing_email=primary_contact.email,
                        billing_phone=primary_contact.phone,
                        billing_street_address=primary_contact.street_address,
                        billing_city=primary_contact.city,
                        billing_province=primary_contact.province,
                        billing_postal_code=primary_contact.postal_code,
                    )
                    forfeited_invoice.save()
                    forfeited_invoice.lesson_items.add(*f_items)
                    forfeited_invoice.amount = forfeited_invoice.calculate_amount()
                    forfeited_invoice.save()
                    student_invoices.append(forfeited_invoice)

            # Phase 20 (D-09): per-student credit deduction/rollover with select_for_update (REC-02)
            # Phase 22 (D-05): waived_items_by_student excluded — no credit written at approval time;
            # waived rollover is deferred to management_generate_teacher_invoice (ADJ-06).
            all_students = (
                set(completed_items_by_student)
                | set(forfeited_items_by_student)
            )

            for student in all_students:
                try:
                    account = StudentCreditAccount.objects.select_for_update().get(
                        student=student, school=batch.school
                    )
                except StudentCreditAccount.DoesNotExist:
                    # get_or_create is race-safe under the unique_together constraint.
                    # Two concurrent batch approvals both reaching DoesNotExist would
                    # cause the second .create() to raise IntegrityError; get_or_create
                    # handles that atomically. The created account starts at balance=0
                    # so subsequent balance arithmetic is correct.
                    account, _ = StudentCreditAccount.objects.get_or_create(
                        student=student,
                        school=batch.school,
                        defaults={'balance': Decimal('0.00')},
                    )
                    # Re-acquire the row lock now that the row is guaranteed to exist.
                    account = StudentCreditAccount.objects.select_for_update().get(
                        student=student, school=batch.school
                    )

                # Confirmed: balance -= amount, NO CreditTransaction (D-01)
                for item in completed_items_by_student.get(student, []):
                    lesson_amount = item.student_rate * item.duration
                    account.balance = max(Decimal('0.00'), account.balance - lesson_amount)

                # Forfeited: balance -= amount, CreditTransaction(type='forfeited') written
                for item in forfeited_items_by_student.get(student, []):
                    lesson_amount = item.student_rate * item.duration
                    if lesson_amount > Decimal('0.00'):
                        account.balance = max(Decimal('0.00'), account.balance - lesson_amount)
                        CreditTransaction.objects.create(
                            account=account, school=batch.school,
                            type='forfeited', amount=lesson_amount,
                        )

                account.save()

            # Phase 20 (D-10, D-11): populate StudentInvoice credit fields via PreBillingInvoice lookup
            period_start = _date(batch.year, batch.month, 1)
            period_end = _date(
                batch.year, batch.month,
                calendar.monthrange(batch.year, batch.month)[1]
            )

            for student_invoice in student_invoices:
                try:
                    pre_invoice = PreBillingInvoice.objects.get(
                        student=student_invoice.student,
                        school=batch.school,
                        period_start=period_start,
                        period_end=period_end,
                    )
                    credit_applied = max(
                        Decimal('0.00'),
                        student_invoice.amount - pre_invoice.amount
                    )
                    amount_after_credit = pre_invoice.amount
                except PreBillingInvoice.DoesNotExist:
                    # D-11 fallback: no PreBillingInvoice → no credit applied
                    credit_applied = Decimal('0.00')
                    amount_after_credit = student_invoice.amount

                student_invoice.credit_applied = credit_applied
                student_invoice.amount_after_credit = amount_after_credit
                student_invoice.save(update_fields=['credit_applied', 'amount_after_credit'])

            # Mark batch as approved
            batch.status = 'approved'
            batch.reviewed_by = request.user
            batch.reviewed_at = timezone.now()
            batch.save()

            # Return JSON for Phase 20 credit reconciliation (HELM-05)
            # CSV is served separately via GET /management/batches/{id}/csv/
            return Response({
                'status': 'approved',
                'batch_id': batch.id,
                'invoice_count': len(student_invoices),
            })

    except Exception as e:
        # Transaction will auto-rollback on exception
        logger.error(f'Batch approval failed: {str(e)}')
        return Response(
            {'error': f'Approval failed: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_batch_csv(request, batch_id):
    """
    Serve the Helcim CSV for an already-approved batch.

    Returns:
        200 HttpResponse with text/csv for approved batches.
        400 if batch.status != 'approved' (D-21: premature download blocked).
        404 if batch not found in user's school (T-18-D1: school isolation).
    """
    from ..models import StudentInvoice, SchoolSettings
    from ..services.helcim_csv_generator import generate_helcim_csv

    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    if batch.status != 'approved':
        return Response(
            {'error': 'Batch must be approved before downloading CSV'},
            status=status.HTTP_400_BAD_REQUEST
        )

    school_settings = SchoolSettings.get_settings_for_school(batch.school)
    student_invoices = list(StudentInvoice.objects.filter(batch=batch))
    return generate_helcim_csv(student_invoices, school_settings)


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

    # Freeze what was actually rejected BEFORE the batch goes back to draft —
    # the live batch keeps evolving (teacher edits, schedule re-sync), so this
    # snapshot is the only record of what the teacher submitted (MAP-99).
    # Atomic + row lock: concurrent rejects must not write duplicate snapshots.
    from django.db import transaction
    with transaction.atomic():
        batch = MonthlyInvoiceBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.status != 'submitted':
            return Response(
                {'error': 'Batch must be in submitted status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        items = list(batch.lesson_items.select_related('student').all())
        BatchRejectionSnapshot.objects.create(
            batch=batch,
            school=batch.school,
            rejected_by=request.user,
            rejection_reason=rejection_reason,
            items=BatchLessonItemSerializer(items, many=True).data,
            total_teacher_payment=sum(
                (item.calculate_teacher_payment() for item in items), Decimal('0.00')
            ),
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_batch_rejection_snapshots(request, batch_id):
    """All rejection snapshots for a batch, newest first (MAP-99 record keeping)."""
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = BatchRejectionSnapshotSerializer(
        batch.rejection_snapshots.select_related('rejected_by'), many=True
    )
    return Response(serializer.data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@management_required
def management_delete_rejected_batch(request, batch_id):
    """
    Hard-delete an abandoned rejected batch.

    Only batches that were rejected (status='draft' with a rejection_reason) and
    were never invoiced may be deleted — these hold no financial records (no
    StudentInvoice / teacher Invoice / credits). Cascade removes the draft
    BatchLessonItems; django-simple-history retains the audit trail. Approved or
    invoiced batches can never be deleted through this endpoint.
    """
    try:
        batch = MonthlyInvoiceBatch.objects.get(id=batch_id, school=request.user.school)
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    is_rejected = batch.status == 'draft' and bool(batch.rejection_reason)
    if not is_rejected or batch.invoice_id is not None:
        return Response(
            {'error': 'Only rejected, never-invoiced batches can be deleted'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    batch.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================================
# MAP-103: Monthly batch archive
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_archive_month(request):
    """
    Archive all finished batches (approved, or rejected drafts) for one month.

    POST body: {"month": 7, "year": 2026}

    Archiving only sets archived_at — nothing is deleted. Lesson items,
    BatchRejectionSnapshot records (MAP-99), linked invoices, and history all
    survive; the batches just leave the Payroll working lists. Submitted and
    clean-draft batches are never archived (still in flight).
    """
    try:
        month = int(request.data.get('month'))
        year = int(request.data.get('year'))
        if not 1 <= month <= 12 or year < 2020:
            raise ValueError
    except (TypeError, ValueError):
        return Response(
            {'error': 'month (1-12) and year are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    finished = (
        MonthlyInvoiceBatch.objects.filter(
            school=request.user.school,
            month=month,
            year=year,
            archived_at__isnull=True,
        )
        .filter(
            Q(status='approved')
            | (Q(status='draft') & ~Q(rejection_reason=''))
        )
    )
    archived = finished.update(archived_at=timezone.now())
    return Response({'archived': archived, 'month': month, 'year': year})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_archived_batches(request):
    """List archived batches, newest archive first. Optional ?month=&year= filter."""
    batches = MonthlyInvoiceBatch.objects.filter(
        school=request.user.school,
        archived_at__isnull=False,
    ).order_by('-archived_at')
    month = request.query_params.get('month')
    year = request.query_params.get('year')
    if month and year:
        try:
            batches = batches.filter(month=int(month), year=int(year))
        except ValueError:
            return Response(
                {'error': 'month and year must be integers'},
                status=status.HTTP_400_BAD_REQUEST,
            )
    serializer = MonthlyInvoiceBatchSerializer(batches, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_unarchive_batch(request, batch_id):
    """Return a single archived batch to the Payroll working lists."""
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id, school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)
    if batch.archived_at is None:
        return Response(
            {'error': 'Batch is not archived'}, status=status.HTTP_400_BAD_REQUEST
        )
    batch.archived_at = None
    batch.save(update_fields=['archived_at', 'updated_at'])
    return Response(MonthlyInvoiceBatchSerializer(batch).data)


# ============================================================================
# PHASE 21: BILLING DASHBOARD ENDPOINTS (DASH-01 through DASH-04)
# ============================================================================

def compute_dashboard_summary(batch, school):
    """
    Compute the three summary card values for a given batch's (year, month) period.

    Aggregates across ALL approved batches for the same school + year + month
    (Pitfall #2: one batch per teacher, not one per period).

    Returns dict with string representations of Decimal values:
      income_pre_expenses  – sum(StudentInvoice.amount) for the period
      expenses_amount      – sum(SchoolExpenseItem.amount) for the period (0.00 if none)
      income_after_expenses – income_pre_expenses - expenses_amount
      income_after_payroll  – income_after_expenses - total_teacher_pay
    """
    period_start = date(batch.year, batch.month, 1)
    period_end = date(batch.year, batch.month, calendar.monthrange(batch.year, batch.month)[1])

    # All approved batches for this school + period (one per teacher)
    period_batches = MonthlyInvoiceBatch.objects.filter(
        status='approved',
        school=school,
        year=batch.year,
        month=batch.month,
    ).select_related('invoice', 'teacher')

    # Student income: sum of StudentInvoice.amount across all period batches
    student_invoices = StudentInvoice.objects.filter(
        batch__in=period_batches,
        school=school,
    )
    income_pre_expenses = sum(
        (inv.amount for inv in student_invoices), Decimal('0.00')
    )

    # Monthly expenses: sum of expense line items for this period
    expense_items = SchoolExpenseItem.objects.filter(
        school=school,
        period_start=period_start,
        period_end=period_end,
    )
    expenses_amount = sum(
        (item.amount for item in expense_items), Decimal('0.00')
    )

    # Teacher payroll: sum of Invoice.total_amount for batches with a linked invoice
    total_teacher_pay = sum(
        (pb.invoice.total_amount or Decimal('0.00') for pb in period_batches if pb.invoice),
        Decimal('0.00'),
    )

    income_after_expenses = income_pre_expenses - expenses_amount
    income_after_payroll = income_after_expenses - total_teacher_pay

    return {
        'income_pre_expenses': str(income_pre_expenses),
        'expenses_amount': str(expenses_amount),
        'income_after_expenses': str(income_after_expenses),
        'income_after_payroll': str(income_after_payroll),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_dashboard_batches(request):
    """
    List unique approved billing periods for the period selector, newest-first.

    Returns one entry per (year, month) — deduplicated across multiple teachers
    (Pitfall #2). Each entry: {batch_id, period_start, period_end, label}.

    DASH-01/02/03/04 period selector (D-07).
    School isolation: filter by request.user.school (T-21-05).
    """
    batches = MonthlyInvoiceBatch.objects.filter(
        status='approved',
        school=request.user.school,
    ).order_by('-year', '-month')

    seen = set()
    result = []
    for batch in batches:
        key = (batch.year, batch.month)
        if key in seen:
            continue
        seen.add(key)
        period_start = date(batch.year, batch.month, 1)
        period_end = date(
            batch.year, batch.month,
            calendar.monthrange(batch.year, batch.month)[1]
        )
        result.append({
            'batch_id': batch.id,
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
            'label': period_start.strftime('%B %Y'),
        })

    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_dashboard_data(request, batch_id):
    """
    Full dashboard data for a billing period: summary cards + student billing + teacher payroll.

    Looks up batch by (id, status='approved', school=request.user.school).
    Aggregates ALL approved batches for the same (school, year, month).

    Returns 404 if batch not found, wrong school, or not approved.

    School isolation: T-21-05 — queryset always scoped to request.user.school.
    """
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            status='approved',
            school=request.user.school,
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    period_start = date(batch.year, batch.month, 1)
    period_end = date(
        batch.year, batch.month,
        calendar.monthrange(batch.year, batch.month)[1]
    )

    # All approved batches for this school + period (one per teacher — Pitfall #2)
    period_batches = MonthlyInvoiceBatch.objects.filter(
        status='approved',
        school=request.user.school,
        year=batch.year,
        month=batch.month,
    ).select_related('invoice', 'teacher')

    # Summary cards
    summary = compute_dashboard_summary(batch, request.user.school)

    # Teacher payroll rows (iterate period_batches — Pitfall #3: Invoice has no batch_id FK)
    teacher_payroll = []
    for pb in period_batches:
        if pb.invoice:
            inv = pb.invoice
            teacher_payroll.append({
                'invoice_id': inv.id,
                'batch_id': pb.id,
                'teacher_id': pb.teacher_id,
                'teacher_name': pb.teacher.get_full_name() or pb.teacher.email,
                'teacher_email': pb.teacher.email,
                'gross': str(inv.total_amount),
                'teacher_pay': str(inv.total_amount),  # A1: gross == teacher_pay in Phase 21
                'paid_status': inv.status,
                'date_paid': inv.date_paid.isoformat() if inv.date_paid else None,
                'reference_number': inv.reference_number,
            })

    # Student billing rows with PreBillingInvoice status lookup
    student_invoices = StudentInvoice.objects.filter(
        batch__in=period_batches,
        school=request.user.school,
    ).select_related('student')

    student_billing = []
    for si in student_invoices:
        pre_billing_status = None
        try:
            pre_inv = PreBillingInvoice.objects.get(
                student=si.student,
                school=request.user.school,
                period_start=period_start,
                period_end=period_end,
            )
            pre_billing_status = pre_inv.status
        except PreBillingInvoice.DoesNotExist:
            pass
        student_billing.append({
            'invoice_id': si.id,
            'student_name': si.student.get_full_name(),
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
            'amount': str(si.amount),
            'credit_applied': str(si.credit_applied),
            'amount_after_credit': str(si.amount_after_credit),
            'lesson_credits': si.lesson_items.count(),
            'pre_billing_status': pre_billing_status,
        })

    return Response({
        'summary': summary,
        'student_billing': student_billing,
        'teacher_payroll': teacher_payroll,
        'period': {
            'batch_id': batch.id,
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
            'label': period_start.strftime('%B %Y'),
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_teacher_invoices(request, teacher_id):
    """
    List a teacher's generated payment invoices for the teacher hub Invoices tab.

    Newest-first, scoped to request.user.school. Each row carries batch_id so the
    frontend can open the frozen billed record (the locked source batch) as the
    dispute record of what was billed.
    """
    invoices = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher_id=teacher_id,
        school=request.user.school,
    ).order_by('-created_at')

    # Map invoice_id -> source batch (period label + record link). batch.invoice is the FK.
    batch_by_invoice = {
        b.invoice_id: b
        for b in MonthlyInvoiceBatch.objects.filter(invoice__in=invoices)
    }

    result = []
    for inv in invoices:
        b = batch_by_invoice.get(inv.id)
        result.append({
            'invoice_id': inv.id,
            'invoice_number': inv.invoice_number,
            'status': inv.status,
            'total_amount': str(inv.total_amount),
            'date_paid': inv.date_paid.isoformat() if inv.date_paid else None,
            'reference_number': inv.reference_number,
            'batch_id': b.id if b else None,
            'period_label': date(b.year, b.month, 1).strftime('%B %Y') if b else None,
        })
    return Response(result)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
@management_required
def management_patch_invoice(request, pk):
    """
    PATCH date_paid, reference_number, and/or status on an invoice.

    Allowlist: only {'date_paid', 'reference_number', 'status'} are writable.
    Non-allowlisted fields in request.data are silently ignored (T-21-07).
    Empty string for nullable fields coerced to None (T-21-08, Pitfall #5).

    Returns 404 if invoice not found in user's school (T-21-10: no 403 to avoid existence disclosure).
    """
    try:
        invoice = Invoice.objects.get(pk=pk, school=request.user.school)
    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

    allowed_fields = {'date_paid', 'reference_number', 'status'}
    fields_to_save = []
    for field in allowed_fields:
        if field in request.data:
            if field == 'status':
                # Validate status against known choices (CR-02)
                valid_statuses = {k for k, _ in Invoice.STATUS_CHOICES}
                if request.data[field] not in valid_statuses:
                    return Response(
                        {'error': f"Invalid status: {request.data[field]!r}. Valid values: {sorted(valid_statuses)}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                # Do NOT apply `or None` coercion — status is a non-null CharField (WR-01)
                setattr(invoice, field, request.data[field])
            else:
                # Empty string → None for nullable fields: date_paid, reference_number (Pitfall #5)
                setattr(invoice, field, request.data[field] or None)
            fields_to_save.append(field)

    if fields_to_save:
        # Use update_fields to bypass Invoice.save() total_amount recalculation
        # (Invoice.save() recalculates total_amount from lessons when pk exists)
        Invoice.objects.filter(pk=invoice.pk).update(
            **{field: getattr(invoice, field) for field in fields_to_save}
        )
    return Response({'status': 'updated'})


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
@management_required
def management_upsert_expenses(request, batch_id):
    """
    Upsert SchoolMonthlyExpenses for the period derived from the given approved batch.

    Validates: amount must be numeric and >= 0 (T-21-09).
    Returns 404 if batch not found / wrong school / not approved.
    Uses update_or_create on (school, period_start, period_end) unique_together.
    """
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            status='approved',
            school=request.user.school,
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    period_start = date(batch.year, batch.month, 1)
    period_end = date(
        batch.year, batch.month,
        calendar.monthrange(batch.year, batch.month)[1]
    )

    amount_raw = request.data.get('amount', '0.00')
    try:
        amount = Decimal(str(amount_raw))
    except Exception:
        return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)

    if amount < Decimal('0.00'):
        return Response(
            {'error': 'Amount must be >= 0'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    obj, _ = SchoolMonthlyExpenses.objects.update_or_create(
        school=request.user.school,
        period_start=period_start,
        period_end=period_end,
        defaults={
            'amount': amount,
            'notes': request.data.get('notes', ''),
        },
    )
    return Response({'amount': str(obj.amount), 'notes': obj.notes})


def _get_batch_period(batch_id, school):
    """Return (batch, period_start, period_end) or raise 404-style exception."""
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            status='approved',
            school=school,
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return None, None, None
    period_start = date(batch.year, batch.month, 1)
    period_end = date(batch.year, batch.month, calendar.monthrange(batch.year, batch.month)[1])
    return batch, period_start, period_end


def _serialize_expense_item(item):
    return {
        'id': item.id,
        'title': item.title,
        'amount': str(item.amount),
        'notes': item.notes,
        'is_recurring': item.is_recurring,
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_expense_items(request, batch_id):
    """
    GET  – list expense items for the period; seeds recurring items from the
           most-recent previous period if this period has none yet.
    POST – create a new expense item for the period.
    """
    school = request.user.school
    batch, period_start, period_end = _get_batch_period(batch_id, school)
    if batch is None:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        items = SchoolExpenseItem.objects.filter(
            school=school, period_start=period_start, period_end=period_end
        )
        if not items.exists():
            # Seed recurring items from most recent prior period
            prev_items = SchoolExpenseItem.objects.filter(
                school=school,
                period_end__lt=period_start,
                is_recurring=True,
            ).order_by('-period_end')
            if prev_items.exists():
                most_recent_end = prev_items.first().period_end
                to_seed = prev_items.filter(period_end=most_recent_end)
                SchoolExpenseItem.objects.bulk_create([
                    SchoolExpenseItem(
                        school=school,
                        period_start=period_start,
                        period_end=period_end,
                        title=item.title,
                        amount=item.amount,
                        notes=item.notes,
                        is_recurring=True,
                    )
                    for item in to_seed
                ])
                items = SchoolExpenseItem.objects.filter(
                    school=school, period_start=period_start, period_end=period_end
                )
        return Response([_serialize_expense_item(i) for i in items])

    # POST
    title = request.data.get('title', '').strip()
    if not title:
        return Response({'error': 'Title is required'}, status=status.HTTP_400_BAD_REQUEST)

    amount_raw = request.data.get('amount', '0.00')
    try:
        amount = Decimal(str(amount_raw))
    except Exception:
        return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)

    if amount < Decimal('0.00'):
        return Response({'error': 'Amount must be >= 0'}, status=status.HTTP_400_BAD_REQUEST)

    item = SchoolExpenseItem.objects.create(
        school=school,
        period_start=period_start,
        period_end=period_end,
        title=title,
        amount=amount,
        notes=request.data.get('notes', ''),
        is_recurring=bool(request.data.get('is_recurring', False)),
    )
    return Response(_serialize_expense_item(item), status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@management_required
def management_expense_item_delete(request, item_id):
    """Delete a single expense line item owned by the caller's school."""
    try:
        item = SchoolExpenseItem.objects.get(id=item_id, school=request.user.school)
    except SchoolExpenseItem.DoesNotExist:
        return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    item.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
