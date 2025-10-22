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
        
        # Create lessons and collect them for the invoice
        created_lessons = []
        
        for lesson_data in lessons_data:
            # Handle student lookup/creation
            student_name = lesson_data.get('student_name')
            student_email = lesson_data.get('student_email')
            
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
                # Try to find existing student by name first
                temp_email = f"{student_name.lower().replace(' ', '.')}@temp.com"
                try:
                    student = User.objects.get(email=temp_email, user_type='student')
                except User.DoesNotExist:
                    # Create new student if not found
                    student = User.objects.create(
                        email=temp_email,
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
                rate=lesson_data.get('rate', request.user.hourly_rate),
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
            due_date=data.get('due_date', timezone.now() + timezone.timedelta(days=30)),
            created_by=request.user,
            payment_balance=0  # Will be calculated after lessons are added
        )
        
        # Add lessons to invoice
        invoice.lessons.set(created_lessons)
        
        # Recalculate payment balance
        invoice.payment_balance = invoice.calculate_payment_balance()
        invoice.save()
        
        # Return the created invoice with lesson details
        serializer = InvoiceSerializer(invoice)
        return Response({
            'message': 'Lessons submitted and invoice created successfully',
            'invoice': serializer.data,
            'lessons_created': len(created_lessons)
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
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