from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.utils import timezone
from ..models import Lesson
from ..serializers import LessonSerializer
from custom_auth.decorators import (
    role_required, teacher_required, teacher_or_management_required
)

User = get_user_model()


# LESSON MANAGEMENT

@api_view(['GET', 'POST'])
@teacher_or_management_required
def lesson_list(request):
    """List and create lessons"""
    if request.method == 'GET':
        if request.user.user_type == 'management':
            lessons = Lesson.objects.filter(school=request.user.school)
        else:  # teacher
            lessons = Lesson.objects.filter(teacher=request.user, school=request.user.school)

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
