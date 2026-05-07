from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from ..models import Invoice, Lesson, BillableContact, RecurringLessonsSchedule
from ..serializers import (
    UserSerializer, LessonSerializer, InvoiceSerializer,
    BillableContactSerializer, StudentCreateSerializer,
    RecurringScheduleSerializer
)
from custom_auth.decorators import (
    role_required, management_required,
    teacher_or_management_required, owns_resource_or_management
)

User = get_user_model()


# DETAIL VIEWS

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
