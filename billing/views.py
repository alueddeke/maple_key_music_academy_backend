from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Invoice, Lesson
from .serializers import UserSerializer, LessonSerializer, InvoiceSerializer
from custom_auth.decorators import (
    role_required, teacher_required, management_required, 
    teacher_or_management_required, owns_resource_or_management
)
from .services.invoice_service import InvoiceProcessor
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
import logging

logger = logging.getLogger(__name__)


#run when url endpoints are hit

User = get_user_model()

# USER MANAGEMENT ENDPOINTS

@extend_schema(
    operation_id='teacher_list',
    summary='List and Create Teachers',
    description='''
    **GET**: Public endpoint to view approved teachers directory.
    
    **POST**: Management-only endpoint to create new teacher accounts.
    Management-created teachers are automatically approved.
    
    ## Authentication
    - GET: No authentication required (public directory)
    - POST: Management role required
    
    ## Business Logic
    - Only approved teachers are visible in the public directory
    - Management can create teachers with auto-approval
    - Teachers created via API are immediately available for lesson requests
    ''',
    tags=['Users'],
    responses={
        200: UserSerializer(many=True),
        201: UserSerializer,
        400: OpenApiTypes.OBJECT,
        403: OpenApiTypes.OBJECT,
    },
    examples=[
        OpenApiExample(
            'Teacher List Response',
            summary='Approved teachers directory',
            description='Public list of approved teachers available for lessons',
            value=[
                {
                    "id": 1,
                    "email": "john.doe@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                    "user_type": "teacher",
                    "bio": "Classical piano instructor with 10+ years experience",
                    "instruments": "Piano, Organ",
                    "hourly_rate": "75.00",
                    "phone_number": "555-0123",
                    "address": "123 Music St, City, State",
                    "is_approved": True
                }
            ],
            response_only=True,
        ),
        OpenApiExample(
            'Create Teacher Request',
            summary='Management creates new teacher',
            description='Request body for creating a new teacher account',
            value={
                "email": "jane.smith@example.com",
                "first_name": "Jane",
                "last_name": "Smith",
                "password": "securepassword123",
                "bio": "Jazz piano and composition instructor",
                "instruments": "Piano, Keyboard, Synthesizer",
                "hourly_rate": "80.00",
                "phone_number": "555-0456",
                "address": "456 Jazz Ave, City, State"
            },
            request_only=True,
        ),
    ]
)
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
            invoices = Invoice.objects.filter(invoice_type='teacher_payment')
        else:  # teacher
            invoices = Invoice.objects.filter(invoice_type='teacher_payment', teacher=request.user)
        
        serializer = InvoiceSerializer(invoices, many=True)
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

@extend_schema(
    operation_id='submit_lessons_for_invoice',
    summary='Submit Lessons for Payment',
    description='''
    Teachers submit completed lesson details and automatically create a payment invoice.
    This is the core billing workflow for teacher compensation.
    
    ## Business Logic
    1. **Lesson Creation**: Creates lesson records for each submitted lesson
    2. **Student Management**: Auto-creates students if they don't exist
    3. **Invoice Generation**: Creates teacher payment invoice
    4. **PDF Generation**: Automatically generates and emails invoice PDF
    5. **Approval Workflow**: Invoice requires management approval for payment
    
    ## Data Validation
    - Student names are required and validated
    - Duration must be positive and reasonable (max 24 hours)
    - Rates are validated if provided
    - Email addresses are validated for student lookup/creation
    
    ## Response
    Returns the created invoice with all lesson details and processing status.
    ''',
    tags=['Invoices'],
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'month': {
                    'type': 'string',
                    'description': 'Billing month description',
                    'example': 'January 2024'
                },
                'lessons': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'student_name': {
                                'type': 'string',
                                'description': 'Full name of the student',
                                'example': 'John Smith'
                            },
                            'student_email': {
                                'type': 'string',
                                'format': 'email',
                                'description': 'Student email (optional, for existing student lookup)',
                                'example': 'john@example.com'
                            },
                            'scheduled_date': {
                                'type': 'string',
                                'format': 'date-time',
                                'description': 'When the lesson was scheduled',
                                'example': '2024-01-15T14:00:00Z'
                            },
                            'duration': {
                                'type': 'number',
                                'format': 'float',
                                'description': 'Lesson duration in hours',
                                'minimum': 0.1,
                                'maximum': 24.0,
                                'example': 1.0
                            },
                            'rate': {
                                'type': 'number',
                                'format': 'float',
                                'description': 'Hourly rate for this lesson (optional, defaults to teacher rate)',
                                'minimum': 0.01,
                                'example': 65.00
                            },
                            'teacher_notes': {
                                'type': 'string',
                                'description': 'Teacher notes about the lesson',
                                'example': 'Worked on scales and arpeggios'
                            }
                        },
                        'required': ['student_name', 'scheduled_date', 'duration']
                    }
                }
            },
            'required': ['lessons']
        }
    },
    responses={
        201: {
            'description': 'Lessons submitted and invoice created successfully',
            'content': {
                'application/json': {
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'message': {'type': 'string'},
                            'invoice': {'$ref': '#/components/schemas/Invoice'},
                            'lessons_created': {'type': 'integer'}
                        }
                    }
                }
            }
        },
        400: {
            'description': 'Validation error in lesson data',
            'content': {
                'application/json': {
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'error': {'type': 'string'},
                            'details': {'type': 'string'}
                        }
                    }
                }
            }
        },
        500: {
            'description': 'Server error during invoice creation',
            'content': {
                'application/json': {
                    'schema': {
                        'type': 'object',
                        'properties': {
                            'error': {'type': 'string'},
                            'details': {'type': 'string'}
                        }
                    }
                }
            }
        }
    },
    examples=[
        OpenApiExample(
            'Submit Lessons Request',
            summary='Teacher submits completed lessons',
            description='Example of submitting multiple completed lessons for payment',
            value={
                "month": "January 2024",
                "lessons": [
                    {
                        "student_name": "John Smith",
                        "student_email": "john@example.com",
                        "scheduled_date": "2024-01-15T14:00:00Z",
                        "duration": 1.0,
                        "rate": 65.00,
                        "teacher_notes": "Worked on scales and arpeggios"
                    },
                    {
                        "student_name": "Sarah Johnson",
                        "scheduled_date": "2024-01-16T10:00:00Z",
                        "duration": 1.5,
                        "rate": 70.00,
                        "teacher_notes": "Advanced technique work"
                    }
                ]
            },
            request_only=True,
        ),
        OpenApiExample(
            'Submit Lessons Response',
            summary='Successful lesson submission',
            description='Response after successfully creating invoice and lessons',
            value={
                "message": "Lessons submitted and invoice created successfully",
                "invoice": {
                    "id": 123,
                    "invoice_type": "teacher_payment",
                    "status": "pending",
                    "payment_balance": "195.00",
                    "teacher": 1,
                    "created_by": 1,
                    "created_at": "2024-01-16T10:30:00Z"
                },
                "lessons_created": 2
            },
            response_only=True,
        )
    ]
)
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
                "rate": 65.00,  # Optional, defaults to teacher's hourly rate
                "teacher_notes": "Worked on scales and arpeggios"
            }
        ],
        "due_date": "2024-02-15T00:00:00Z"
    }
    """
    try:
        # Handle malformed JSON
        try:
            data = request.data.copy()
        except Exception as e:
            return Response({'error': 'Invalid JSON format'}, status=status.HTTP_400_BAD_REQUEST)
        
        lessons_data = data.get('lessons', [])
        
        if not lessons_data:
            return Response({'error': 'No lessons provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Create lessons and collect them for the invoice
        created_lessons = []
        
        for lesson_data in lessons_data:
            # Validate lesson data
            student_name = lesson_data.get('student_name', '').strip()
            student_email = lesson_data.get('student_email')
            duration = lesson_data.get('duration', 0)
            
            # Validate required fields
            if not student_name:
                return Response({'error': 'Student name is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate duration
            if duration is None:
                return Response({'error': 'Duration is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                duration = float(duration)
            except (ValueError, TypeError):
                return Response({'error': 'Duration must be a valid number'}, status=status.HTTP_400_BAD_REQUEST)
            
            if duration <= 0:
                return Response({'error': 'Duration must be greater than 0'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate duration is reasonable (not too high)
            if duration > 24:  # More than 24 hours seems unreasonable
                return Response({'error': 'Duration is too high (maximum 24 hours)'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate student name length (more reasonable limit)
            if len(student_name) > 150:
                return Response({'error': 'Student name is too long (maximum 150 characters)'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate rate if provided
            rate = lesson_data.get('rate')
            if rate is not None:
                if rate <= 0:
                    return Response({'error': 'Rate must be greater than 0'}, status=status.HTTP_400_BAD_REQUEST)
            
            if student_email:
                # Try to find existing student by email
                try:
                    student = User.objects.get(email=student_email, user_type='student')
                except User.DoesNotExist:
                    # Create new student if not found
                    student = User.objects.create(
                        email=student_email,
                        first_name=student_name.split()[0] if student_name else '',
                        last_name=' '.join(student_name.split()[1:]) if student_name and len(student_name.split()) > 1 else '',
                        user_type='student',
                        is_approved=True  # Auto-approve students created by teachers
                    )
            else:
                # Create student with just name (no email)
                # First try to find existing student by name
                try:
                    student = User.objects.get(
                        first_name=student_name.split()[0] if student_name else '',
                        last_name=' '.join(student_name.split()[1:]) if student_name and len(student_name.split()) > 1 else '',
                        user_type='student'
                    )
                except User.DoesNotExist:
                    # Create new student with unique temporary email
                    base_email = f"{student_name.lower().replace(' ', '.')}@temp.com"
                    counter = 1
                    unique_email = base_email
                    
                    # Ensure email is unique by adding counter if needed
                    while User.objects.filter(email=unique_email).exists():
                        unique_email = f"{student_name.lower().replace(' ', '.')}{counter}@temp.com"
                        counter += 1
                    
                    student = User.objects.create(
                        email=unique_email,
                        first_name=student_name.split()[0] if student_name else '',
                        last_name=' '.join(student_name.split()[1:]) if student_name and len(student_name.split()) > 1 else '',
                        user_type='student',
                        is_approved=True
                    )
            
            # Create lesson
            lesson = Lesson.objects.create(
                teacher=request.user,
                student=student,
                scheduled_date=lesson_data.get('scheduled_date', timezone.now()),
                duration=lesson_data.get('duration', 1.0),
                rate=lesson_data.get('rate', 65.00),  # Use default rate of 65.00 instead of teacher's hourly_rate
                status='completed',  # Mark as completed since teacher is submitting for payment
                completed_date=timezone.now(),
                teacher_notes=lesson_data.get('teacher_notes', '')
            )
            
            created_lessons.append(lesson)
        
        # Create invoice
        invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=request.user,
            status='pending',  # Ready for management approval
            # due_date=data.get('due_date', timezone.now() + timezone.timedelta(days=30)),  # Commented out
            created_by=request.user,
            payment_balance=0  # Will be calculated after lessons are added
        )
        
        # Add lessons to invoice
        invoice.lessons.set(created_lessons)
        
        # Recalculate payment balance
        invoice.payment_balance = invoice.calculate_payment_balance()
        invoice.save()
        
        # Generate PDF and send email
        try:
            success, message, pdf_content = InvoiceProcessor.generate_and_send_invoice(invoice)
            if success:
                logger.info(f"PDF generated and email sent for invoice {invoice.id}")
            else:
                logger.warning(f"Failed to generate PDF or send email for invoice {invoice.id}: {message}")
        except Exception as e:
            logger.error(f"Error generating PDF or sending email for invoice {invoice.id}: {str(e)}")
        
        # Return the created invoice with lesson details
        serializer = InvoiceSerializer(invoice)
        return Response({
            'message': 'Lessons submitted and invoice created successfully',
            'invoice': serializer.data,
            'lessons_created': len(created_lessons)
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
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