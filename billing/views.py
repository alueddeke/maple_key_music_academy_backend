from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Invoice, Lesson, BillableContact
from .serializers import (
    UserSerializer, LessonSerializer, InvoiceSerializer, DetailedInvoiceSerializer,
    BillableContactSerializer, StudentCreateSerializer
)
from custom_auth.decorators import (
    role_required, teacher_required, management_required,
    teacher_or_management_required, owns_resource_or_management
)
import logging

logger = logging.getLogger(__name__)


#run when url endpoints are hit

User = get_user_model()

# USER MANAGEMENT ENDPOINTS

@api_view(['GET', 'POST'])
def teacher_list(request):
    """Public teacher directory + management teacher creation"""
    if request.method == 'GET':
        # Public endpoint - show approved teachers only
        teachers = User.objects.filter(user_type='teacher', is_approved=True)
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
    teachers = User.objects.filter(user_type='teacher')
    serializer = UserSerializer(teachers, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@management_required  
def approve_teacher(request, teacher_id):
    """Management endpoint to approve pending teachers"""
    try:
        teacher = User.objects.get(id=teacher_id, user_type='teacher')
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
        students = User.objects.filter(user_type='student')
    else:
        students = User.objects.filter(id=request.user.id)
    
    serializer = UserSerializer(students, many=True)
    return Response(serializer.data)

# LESSON MANAGEMENT

@api_view(['GET', 'POST'])
@teacher_or_management_required
def lesson_list(request):
    """List and create lessons"""
    if request.method == 'GET':
        if request.user.user_type == 'management':
            lessons = Lesson.objects.all()
        else:  # teacher
            lessons = Lesson.objects.filter(teacher=request.user)
        
        serializer = LessonSerializer(lessons, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        data = request.data.copy()
        
        if request.user.user_type == 'teacher':
            # Teachers can only create lessons for themselves
            data['teacher'] = request.user.id
        elif request.user.user_type == 'management':
            # Management can create lessons for any teacher
            if 'teacher' not in data:
                return Response({'error': 'Teacher ID required'}, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = LessonSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@role_required('student')
def request_lesson(request):
    """Students can request lessons from teachers"""
    data = request.data.copy()
    data['student'] = request.user.id
    data['status'] = 'requested'
    
    # Validate teacher exists and is approved
    teacher_id = data.get('teacher')
    try:
        teacher = User.objects.get(id=teacher_id, user_type='teacher', is_approved=True)
    except User.DoesNotExist:
        return Response({'error': 'Teacher not found or not approved'}, status=status.HTTP_400_BAD_REQUEST)
    
    serializer = LessonSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@teacher_required
def confirm_lesson(request, lesson_id):
    """Teachers can confirm student lesson requests"""
    try:
        lesson = Lesson.objects.get(id=lesson_id, teacher=request.user, status='requested')
        lesson.status = 'confirmed'
        lesson.save()
        return Response({'message': 'Lesson confirmed'})
    except Lesson.DoesNotExist:
        return Response({'error': 'Lesson request not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])  
@teacher_required
def complete_lesson(request, lesson_id):
    """Teachers mark lessons as completed"""
    try:
        lesson = Lesson.objects.get(id=lesson_id, teacher=request.user, status='confirmed')
        lesson.status = 'completed'
        lesson.completed_date = timezone.now()
        lesson.teacher_notes = request.data.get('notes', '')
        lesson.save()
        return Response({'message': 'Lesson marked as completed'})
    except Lesson.DoesNotExist:
        return Response({'error': 'Confirmed lesson not found'}, status=status.HTTP_404_NOT_FOUND)

# INVOICE MANAGEMENT

@api_view(['GET', 'POST'])
@teacher_or_management_required
def teacher_invoice_list(request):
    """Teacher payment invoices"""
    if request.method == 'GET':
        if request.user.user_type == 'management':
            invoices = Invoice.objects.filter(invoice_type='teacher_payment').order_by('-created_at')
        else:  # teacher
            invoices = Invoice.objects.filter(invoice_type='teacher_payment', teacher=request.user).order_by('-created_at')

        # Use DetailedInvoiceSerializer to include lesson details
        serializer = DetailedInvoiceSerializer(invoices, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        # Create teacher payment invoice
        data = request.data.copy()
        data['invoice_type'] = 'teacher_payment'
        
        if request.user.user_type == 'teacher':
            data['teacher'] = request.user.id
            data['created_by'] = request.user.id
        
        serializer = InvoiceSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@teacher_required
def teacher_invoice_stats(request):
    """Get teacher's invoice statistics including rejected count"""
    teacher = request.user

    # Get counts by status
    pending_count = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        status='pending'
    ).count()

    rejected_count = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        status='rejected'
    ).count()

    approved_count = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        status='approved'
    ).count()

    paid_count = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        status='paid'
    ).count()

    # Get most recent rejected invoices
    recent_rejected = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        status='rejected'
    ).order_by('-rejected_at')[:5]

    rejected_invoices = []
    for invoice in recent_rejected:
        rejected_invoices.append({
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'total_amount': str(invoice.total_amount),
            'rejected_at': invoice.rejected_at,
            'rejected_by_name': invoice.rejected_by.get_full_name() if invoice.rejected_by else None,
            'rejection_reason': invoice.rejection_reason,
        })

    return Response({
        'pending_count': pending_count,
        'rejected_count': rejected_count,
        'approved_count': approved_count,
        'paid_count': paid_count,
        'recent_rejected': rejected_invoices,
    })

@api_view(['POST'])
@teacher_required
def submit_lessons_for_invoice(request):
    """
    Teacher submits lesson details and creates invoice in one transaction.
    
    Expected request body:
    {
        "month": "January 2024",
        "lessons": [
            {
                "student_name": "John Smith",
                "student_email": "john@example.com",  # Optional, for student lookup
                "scheduled_date": "2024-01-15T14:00:00Z",
                "duration": 1.0,
                "rate": 80.00,  # Optional, defaults to teacher's hourly rate
                "teacher_notes": "Worked on scales and arpeggios"
            }
        ],
        "due_date": "2024-02-15T00:00:00Z"
    }
    """
    try:
        data = request.data.copy()
        lessons_data = data.get('lessons', [])

        if not lessons_data:
            return Response({'error': 'No lessons provided'}, status=status.HTTP_400_BAD_REQUEST)

        # VALIDATION: Check all students have complete billing information
        validation_errors = []
        for lesson_data in lessons_data:
            student_email = lesson_data.get('student_email')
            student_name = lesson_data.get('student_name', 'Unknown Student')

            # Generate email if not provided (same logic as creation)
            if not student_email:
                temp_email = f"{student_name.lower().replace(' ', '.')}@temp.com"
                student_email = temp_email

            # Check if student exists
            try:
                student = User.objects.get(email=student_email, user_type='student')

                # Check for complete billing contact
                primary_contact = BillableContact.objects.filter(
                    student=student,
                    is_primary=True
                ).first()

                if not primary_contact:
                    validation_errors.append({
                        'student': student_name,
                        'email': student_email,
                        'error': 'No billing contact found. Please add complete billing information in Student Management.'
                    })
                else:
                    # Check all required fields
                    missing_fields = []
                    incomplete_fields = {}

                    # Handle both old 'state' and new 'province' field names for backward compatibility
                    province_value = getattr(primary_contact, 'province', None) or getattr(primary_contact, 'state', None)

                    required_fields = {
                        'first_name': primary_contact.first_name,
                        'last_name': primary_contact.last_name,
                        'email': primary_contact.email,
                        'phone': primary_contact.phone,
                        'street_address': primary_contact.street_address,
                        'city': primary_contact.city,
                        'province': province_value,
                        'postal_code': primary_contact.postal_code
                    }

                    for field_name, field_value in required_fields.items():
                        if not field_value or field_value.strip() == '':
                            missing_fields.append(field_name)
                        elif field_value.strip().upper() in ['INCOMPLETE', 'XX', 'N/A', 'TBD']:
                            incomplete_fields[field_name] = field_value

                    if missing_fields or incomplete_fields:
                        error_parts = []
                        if missing_fields:
                            error_parts.append(f"Missing: {', '.join(missing_fields)}")
                        if incomplete_fields:
                            error_parts.append(f"Incomplete: {', '.join(incomplete_fields.keys())}")

                        validation_errors.append({
                            'student': student_name,
                            'email': student_email,
                            'missing_fields': missing_fields,
                            'incomplete_fields': list(incomplete_fields.keys()),
                            'error': f"Incomplete billing contact. {' | '.join(error_parts)}. Please update student information in Student Management."
                        })

            except User.DoesNotExist:
                # New student - will be created, so skip validation for now
                # Will create with placeholder contact that must be updated before invoice approval
                pass

        # If validation errors found, return them with helpful message
        if validation_errors:
            return Response({
                'error': 'Cannot submit invoice - some students have incomplete billing information',
                'details': validation_errors,
                'message': 'Please update student billing information in Student Management before submitting this invoice. All fields (name, email, phone, street address, city, province, postal code) are required.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Create lessons and collect them for the invoice
        created_lessons = []

        for lesson_data in lessons_data:
            # Handle student lookup/creation
            student_name = lesson_data.get('student_name')
            student_email = lesson_data.get('student_email')
            
            if student_email:
                # Find or create student by email using get_or_create for atomicity
                student, created = User.objects.get_or_create(
                    email=student_email,
                    user_type='student',
                    defaults={
                        'first_name': student_name.split()[0] if student_name else '',
                        'last_name': ' '.join(student_name.split()[1:]) if student_name and len(student_name.split()) > 1 else '',
                        'is_approved': True  # Auto-approve students created by teachers
                    }
                )
            else:
                # Create student with just name (no email)
                # Generate temp email and use get_or_create for atomicity
                temp_email = f"{student_name.lower().replace(' ', '.')}@temp.com"
                student, created = User.objects.get_or_create(
                    email=temp_email,
                    user_type='student',
                    defaults={
                        'first_name': student_name.split()[0] if student_name else '',
                        'last_name': ' '.join(student_name.split()[1:]) if student_name and len(student_name.split()) > 1 else '',
                        'is_approved': True
                    }
                )

            # If student was just created, create a placeholder billable contact
            # Management must complete this information before approving the invoice
            if created:
                # Handle both old 'state' and new 'province' field names for backward compatibility
                contact_data = {
                    'student': student,
                    'contact_type': 'parent',
                    'first_name': 'INCOMPLETE',
                    'last_name': 'INCOMPLETE',
                    'email': student_email or temp_email,
                    'phone': 'INCOMPLETE',
                    'street_address': 'INCOMPLETE - Please update in Student Management',
                    'city': 'INCOMPLETE',
                    'postal_code': 'INCOMPLETE',
                    'is_primary': True
                }

                # Detect which field name to use (province vs state) for backward compatibility
                try:
                    BillableContact._meta.get_field('province')
                    contact_data['province'] = 'XX'
                except:
                    contact_data['state'] = 'XX'

                BillableContact.objects.create(**contact_data)
            
            # Create lesson with dual-rate system
            lesson_type = lesson_data.get('lesson_type', 'in_person')  # Default to in_person for backward compatibility

            # Determine rates based on lesson type
            from billing.models import GlobalRateSettings
            from decimal import Decimal

            global_rates = GlobalRateSettings.get_settings()

            if lesson_type == 'online':
                # Online lessons use global rates
                teacher_rate = global_rates.online_teacher_rate
                student_rate = global_rates.online_student_rate
            else:
                # In-person lessons: teacher gets their hourly_rate, student pays global in-person rate
                teacher_rate = request.user.hourly_rate
                student_rate = global_rates.inperson_student_rate


            # Determine trial status
            if 'is_trial' in lesson_data:
                # Teacher explicitly set trial status - respect their choice
                is_trial = lesson_data.get('is_trial', False)
                explicitly_set = True
                logger.info(f"Teacher explicitly set is_trial={is_trial} for student {student.email}")
            else:
                # No explicit setting - auto-detect based on student history
                if not Lesson.student_has_completed_lesson(student):
                    is_trial = True
                    logger.info(f"Auto-detected first lesson for student {student.email} - marking as trial")
                else:
                    is_trial = False
                explicitly_set = False

            if is_trial:
                student_rate = Decimal('0.00')
                logger.info(f"Trial lesson for {student.email} - student_rate=$0.00, teacher_rate={teacher_rate}")

            # Create lesson
            lesson = Lesson(
                teacher=request.user,
                student=student,
                lesson_type=lesson_type,
                is_trial=is_trial,
                scheduled_date=lesson_data.get('scheduled_date', timezone.now()),
                duration=lesson_data.get('duration', 1.0),
                teacher_rate=teacher_rate,
                student_rate=student_rate,
                status='completed',  # Mark as completed since teacher is submitting for payment
                completed_date=timezone.now(),
                teacher_notes=lesson_data.get('teacher_notes', '')
            )

            # Mark if trial status was explicitly set (to prevent auto-detection override in save())
            if explicitly_set:
                lesson._is_trial_explicitly_set = True

            # Save the lesson
            lesson.save()

            created_lessons.append(lesson)
        
        # Create invoice
        invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=request.user,
            status='pending',  # Ready for management approval
            due_date=data.get('due_date', timezone.now() + timezone.timedelta(days=14)),  # 2 weeks
            created_by=request.user,
            payment_balance=0  # Will be calculated after lessons are added
        )
        
        # Add lessons to invoice
        invoice.lessons.set(created_lessons)

        # Recalculate payment balance and total amount
        calculated_total = invoice.calculate_payment_balance()
        invoice.payment_balance = calculated_total
        invoice.total_amount = calculated_total
        invoice.save()

        # Create student invoices
        # Group lessons by student
        from collections import defaultdict
        lessons_by_student = defaultdict(list)
        for lesson in created_lessons:
            lessons_by_student[lesson.student].append(lesson)

        student_invoices_created = []
        for student, student_lessons in lessons_by_student.items():
            # Calculate total for this student using student_rate (not teacher_rate)
            student_total = sum(lesson.student_cost() for lesson in student_lessons)

            # Create student invoice
            student_invoice = Invoice.objects.create(
                invoice_type='student_billing',
                student=student,
                status='pending',  # Waiting for student payment
                due_date=timezone.now() + timezone.timedelta(days=14),  # 14 days payment term
                created_by=request.user,
                payment_balance=student_total,
                total_amount=student_total
            )

            # Add lessons to student invoice
            student_invoice.lessons.set(student_lessons)
            student_invoices_created.append(student_invoice)

        # Generate PDF and send email
        try:
            from billing.services.teacher_invoicepdf_generator import InvoiceProcessor
            success, message, pdf_content = InvoiceProcessor.generate_and_send_invoice(invoice)
            if success:
                logger.info(f"PDF generated and email sent for invoice {invoice.id} with {len(student_invoices_created)} student invoices")
            else:
                logger.warning(f"Failed to generate PDF or send email for invoice {invoice.id}: {message}")
        except Exception as e:
            logger.error(f"Error generating PDF or sending email for invoice {invoice.id}: {str(e)}")

        # Return the created invoice with lesson details
        serializer = InvoiceSerializer(invoice)
        return Response({
            'message': 'Lessons submitted and invoice created successfully',
            'invoice': serializer.data,
            'lessons_created': len(created_lessons),
            'student_invoices_created': len(student_invoices_created)
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        import traceback
        logger.error(f"Invoice submission failed: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return Response({
            'error': 'Failed to create invoice',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@management_required
def approve_teacher_invoice(request, invoice_id):
    """Management approves teacher payment invoices"""
    try:
        invoice = Invoice.objects.get(id=invoice_id, invoice_type='teacher_payment')
        invoice.status = 'approved'
        invoice.approved_by = request.user
        invoice.approved_at = timezone.now()
        invoice.save()
        return Response({'message': 'Invoice approved'})
    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

# DETAIL VIEWS

@api_view(['GET', 'PUT', 'DELETE'])
def teacher_detail(request, pk):
    """Teacher detail endpoint - GET is public, PUT/DELETE require authentication"""
    try:
        teacher = User.objects.get(pk=pk, user_type='teacher')
    except User.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        # Allow anyone to view teacher details (public profile)
        serializer = UserSerializer(teacher)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        # Require authentication to update teacher profile
        if not request.user.is_authenticated:
            return Response({
                'error': 'Authentication required',
                'message': 'Please provide a valid JWT token to update teacher profile'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Check if the authenticated user is updating their own profile or is management
        if request.user.id != teacher.id and request.user.user_type != 'management':
            return Response({
                'error': 'Access denied',
                'message': 'You can only update your own profile'
            }, status=status.HTTP_403_FORBIDDEN)
        
        serializer = UserSerializer(teacher, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        # Require management to delete teacher profiles
        if not request.user.is_authenticated or request.user.user_type != 'management':
            return Response({
                'error': 'Management access required',
                'message': 'Only management can delete teacher profiles'
            }, status=status.HTTP_403_FORBIDDEN)
        
        teacher.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'PUT', 'DELETE'])
@role_required('student', 'management')
def student_detail(request, pk):
    """Student detail endpoint - students can see themselves, management can see all"""
    try:
        if request.user.user_type == 'management':
            student = User.objects.get(pk=pk, user_type='student')
        else:  # student
            student = User.objects.get(pk=pk, user_type='student', id=request.user.id)
    except User.DoesNotExist:
        return Response({
            'error': 'Student not found or access denied'
        }, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = UserSerializer(student)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        # Students can only update their own profile, management can update any
        if request.user.user_type != 'management' and request.user.id != student.id:
            return Response({
                'error': 'Access denied',
                'message': 'You can only update your own profile'
            }, status=status.HTTP_403_FORBIDDEN)
        
        serializer = UserSerializer(student, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        # Only management can delete student profiles
        if request.user.user_type != 'management':
            return Response({
                'error': 'Management access required',
                'message': 'Only management can delete student profiles'
            }, status=status.HTTP_403_FORBIDDEN)
        
        student.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'PUT', 'DELETE'])
@teacher_or_management_required
def lesson_detail(request, pk):
    """Lesson detail endpoint - teachers can see their own, management can see all"""
    try:
        if request.user.user_type == 'management':
            lesson = Lesson.objects.get(pk=pk)
        else:  # teacher
            lesson = Lesson.objects.get(pk=pk, teacher=request.user)
    except Lesson.DoesNotExist:
        return Response({
            'error': 'Lesson not found or access denied'
        }, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = LessonSerializer(lesson)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        # Ensure the lesson still belongs to this teacher after update (unless management)
        data = request.data.copy()
        if request.user.user_type == 'teacher':
            data['teacher'] = request.user.id
        
        serializer = LessonSerializer(lesson, data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        lesson.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'PUT', 'DELETE'])
@teacher_or_management_required
def invoice_detail(request, pk):
    """Invoice detail endpoint - teachers can see their own, management can see all"""
    try:
        if request.user.user_type == 'management':
            invoice = Invoice.objects.get(pk=pk)
        else:  # teacher
            invoice = Invoice.objects.get(pk=pk, teacher=request.user)
    except Invoice.DoesNotExist:
        return Response({
            'error': 'Invoice not found or access denied'
        }, status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = InvoiceSerializer(invoice)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        # Ensure the invoice still belongs to this teacher after update (unless management)
        data = request.data.copy()
        if request.user.user_type == 'teacher':
            data['teacher'] = request.user.id
        
        serializer = InvoiceSerializer(invoice, data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        invoice.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# MANAGEMENT ENDPOINTS FOR USER APPROVAL SYSTEM

@api_view(['GET', 'POST'])
@management_required
def approved_email_list(request):
    """Management can view and add pre-approved emails"""
    from .models import ApprovedEmail
    from .serializers import ApprovedEmailSerializer
    from .invitation_utils import create_and_send_invitation

    if request.method == 'GET':
        approved_emails = ApprovedEmail.objects.all()
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
    from .models import ApprovedEmail

    try:
        approved_email = ApprovedEmail.objects.get(pk=pk)
        approved_email.delete()
        return Response({'message': 'Approved email deleted successfully'}, status=status.HTTP_204_NO_CONTENT)
    except ApprovedEmail.DoesNotExist:
        return Response({'error': 'Approved email not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@management_required
def registration_request_list(request):
    """Management can view all registration requests"""
    from .models import UserRegistrationRequest
    from .serializers import UserRegistrationRequestSerializer

    # Filter by status if provided
    status_filter = request.GET.get('status')
    if status_filter:
        requests = UserRegistrationRequest.objects.filter(status=status_filter)
    else:
        requests = UserRegistrationRequest.objects.all()

    serializer = UserRegistrationRequestSerializer(requests, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@management_required
def approve_registration_request(request, pk):
    """Management approves a registration request and sends invitation email"""
    from .models import UserRegistrationRequest, ApprovedEmail, InvitationToken
    from .invitation_utils import generate_invitation_token, send_invitation_email

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
            print(f"WARNING: Failed to send invitation email to {reg_request.email}: {message}")

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
    from .models import UserRegistrationRequest

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
    from .serializers import DetailedUserSerializer

    # Filter by user_type if provided
    user_type = request.GET.get('user_type')
    approval_status = request.GET.get('is_approved')

    users = User.objects.all()

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
        user = User.objects.get(pk=pk)

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


# INVITATION TOKEN ENDPOINTS

@api_view(['GET'])
@permission_classes([AllowAny])  # Public endpoint - no authentication required
def validate_invitation_token(request, token):
    """Validate invitation token and return email/user_type if valid"""
    from .models import InvitationToken

    try:
        invitation = InvitationToken.objects.get(token=token)

        if not invitation.is_valid():
            return Response({
                'error': 'Invalid or expired invitation token',
                'is_used': invitation.is_used,
                'is_expired': timezone.now() >= invitation.expires_at
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'valid': True,
            'email': invitation.email,
            'user_type': invitation.user_type,
            'user_type_display': invitation.get_user_type_display(),
            'expires_at': invitation.expires_at
        })

    except InvitationToken.DoesNotExist:
        return Response({
            'error': 'Invalid invitation token'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([AllowAny])  # Public endpoint - no authentication required
def setup_account_with_invitation(request, token):
    """Create user account using invitation token"""
    from .models import InvitationToken, User

    try:
        invitation = InvitationToken.objects.get(token=token)

        # Validate token
        if not invitation.is_valid():
            return Response({
                'error': 'Invalid or expired invitation token'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Check if user already exists
        if User.objects.filter(email=invitation.email).exists():
            return Response({
                'error': 'An account with this email already exists'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Get user data from request
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        password = request.data.get('password')

        if not first_name or not last_name:
            return Response({
                'error': 'First name and last name are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Create user account
        user = User.objects.create_user(
            email=invitation.email,
            password=password if password else None,  # Password is optional (for OAuth users)
            first_name=first_name,
            last_name=last_name,
            user_type=invitation.user_type,
        )
        user.is_approved = True  # Pre-approved via invitation
        user.save()

        # Mark token as used
        invitation.mark_as_used()

        # Generate JWT tokens for immediate login
        from rest_framework_simplejwt.tokens import RefreshToken
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

    except InvitationToken.DoesNotExist:
        return Response({
            'error': 'Invalid invitation token'
        }, status=status.HTTP_404_NOT_FOUND)


# MANAGEMENT ENDPOINTS FOR INVOICE MANAGEMENT

@api_view(['GET'])
@management_required
def management_all_invoices(request):
    """Management can view all invoices with detailed information"""
    from .serializers import DetailedInvoiceSerializer

    # Filters
    invoice_type = request.GET.get('invoice_type')
    status_filter = request.GET.get('status')
    teacher_id = request.GET.get('teacher_id')

    invoices = Invoice.objects.all().order_by('-created_at')  # Newest first

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
    from .serializers import DetailedInvoiceSerializer

    try:
        invoice = Invoice.objects.get(pk=pk)

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
        invoice = Invoice.objects.get(pk=pk)
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
        invoice = Invoice.objects.get(pk=pk)

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
        invoice = Invoice.objects.get(pk=pk)
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


@api_view(['POST'])
@management_required
def management_regenerate_invoice_pdf(request, pk):
    """Management can regenerate and resend invoice PDF"""
    try:
        from billing.services.teacher_invoicepdf_generator import InvoiceProcessor

        invoice = Invoice.objects.get(pk=pk)

        # Get recipient email if provided
        recipient_email = request.data.get('recipient_email')

        # Regenerate PDF and send email
        success, message, pdf_content = InvoiceProcessor.generate_and_send_invoice(
            invoice, recipient_email
        )

        if success:
            return Response({
                'message': 'Invoice PDF regenerated and sent successfully'
            })
        else:
            return Response({
                'error': 'Failed to regenerate invoice',
                'details': message
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)


# SYSTEM SETTINGS ENDPOINTS

@api_view(['GET'])
@management_required
def get_system_settings(request):
    """Get system settings (management only)"""
    from .models import SystemSettings
    from .serializers import SystemSettingsSerializer

    settings = SystemSettings.get_settings()
    serializer = SystemSettingsSerializer(settings)
    return Response(serializer.data)


@api_view(['PUT'])
@management_required
def update_system_settings(request):
    """Update system settings (management only)"""
    from .models import SystemSettings
    from .serializers import SystemSettingsSerializer

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
    from .models import InvoiceRecipientEmail
    from .serializers import InvoiceRecipientEmailSerializer

    recipients = InvoiceRecipientEmail.objects.all()
    serializer = InvoiceRecipientEmailSerializer(recipients, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@management_required
def add_invoice_recipient(request):
    """Add a new invoice recipient email (management only)"""
    from .models import InvoiceRecipientEmail
    from .serializers import InvoiceRecipientEmailSerializer

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
    from .models import InvoiceRecipientEmail

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
def global_rate_settings(request):
    """
    Get or update global rate settings (singleton).
    Management only.
    """
    from .models import GlobalRateSettings
    from .serializers import GlobalRateSettingsSerializer

    # Get or create the singleton settings instance
    settings = GlobalRateSettings.get_settings()

    if request.method == 'GET':
        serializer = GlobalRateSettingsSerializer(settings)
        return Response(serializer.data)

    elif request.method == 'PATCH':
        serializer = GlobalRateSettingsSerializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(updated_by=request.user)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@management_required
def teacher_list(request):
    """
    List all teachers with computed stats.
    Management only.
    """
    from .serializers import TeacherListSerializer

    teachers = User.objects.filter(user_type='teacher', is_approved=True).order_by('last_name', 'first_name')
    serializer = TeacherListSerializer(teachers, many=True)
    return Response(serializer.data)


@api_view(['GET', 'PATCH'])
@management_required
def teacher_detail(request, pk):
    """
    Get teacher details with stats, or update teacher hourly_rate.
    Management only.
    """
    from .serializers import TeacherDetailSerializer

    try:
        teacher = User.objects.get(pk=pk, user_type='teacher')
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

        # Return updated teacher data
        serializer = TeacherDetailSerializer(teacher)
        return Response(serializer.data)

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
            students = User.objects.filter(user_type='student')
        else:
            students = User.objects.filter(user_type='student', is_active=True)
        
        serializer = UserSerializer(students, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        # Create student with billing contact
        serializer = StudentCreateSerializer(data=request.data)
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
        student = User.objects.get(pk=pk, user_type='student')
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
        student = User.objects.get(pk=student_id, user_type='student', is_active=True)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
    
    data = request.data.copy()
    data['student'] = student.id
    
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
        contact = BillableContact.objects.get(pk=pk)
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
# TEACHER-STUDENT ASSIGNMENT ENDPOINTS
# ============================================================================

@api_view(['POST'])
@management_required
def assign_teachers_to_student(request, student_id):
    """Assign one or more teachers to a student"""
    try:
        student = User.objects.get(pk=student_id, user_type='student', is_active=True)
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
        student = User.objects.get(pk=student_id, user_type='student')
        teacher = User.objects.get(pk=teacher_id, user_type='teacher')
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
        teacher = User.objects.get(pk=teacher_id, user_type='teacher')
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
        teacher = User.objects.get(pk=pk, user_type='teacher')
    except User.DoesNotExist:
        return Response({'error': 'Teacher not found'}, status=status.HTTP_404_NOT_FOUND)
    
    serializer = UserSerializer(teacher, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
@management_required
def management_delete_teacher(request, pk):
    """Soft delete a teacher"""
    try:
        teacher = User.objects.get(pk=pk, user_type='teacher')
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
