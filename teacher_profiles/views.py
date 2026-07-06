from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from custom_auth.decorators import teacher_or_management_required

from .models import TeacherAvailability, TeacherInstrument, TeacherProfile
from .serializers import (
    TeacherAvailabilitySerializer,
    TeacherInstrumentSerializer,
    TeacherProfileSerializer,
)

User = get_user_model()


def _resolve_profile(request, teacher_id):
    """Resolve the target teacher's profile, enforcing access rules.

    - Teachers may only access their own profile (403 otherwise).
    - Management may access any teacher in their own school (404 otherwise).
    Returns (profile, None) on success or (None, error_response).
    """
    if request.user.user_type == 'teacher' and request.user.id != teacher_id:
        return None, Response(
            {'error': 'You may only access your own profile'},
            status=status.HTTP_403_FORBIDDEN,
        )

    teacher = User.objects.filter(
        pk=teacher_id, user_type='teacher', school=request.user.school
    ).first()
    if teacher is None:
        return None, Response(
            {'error': 'Teacher not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    profile, _ = TeacherProfile.objects.get_or_create(
        teacher=teacher, defaults={'school': teacher.school}
    )
    return profile, None


@api_view(['GET', 'PUT'])
@teacher_or_management_required
def teacher_profile_detail(request, teacher_id):
    """GET the full profile (nested instruments + availability) or PUT profile fields."""
    profile, error = _resolve_profile(request, teacher_id)
    if error:
        return error

    if request.method == 'GET':
        return Response(TeacherProfileSerializer(profile).data)

    serializer = TeacherProfileSerializer(profile, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
@teacher_or_management_required
def teacher_instrument_list(request, teacher_id):
    profile, error = _resolve_profile(request, teacher_id)
    if error:
        return error

    if request.method == 'GET':
        serializer = TeacherInstrumentSerializer(profile.instruments.all(), many=True)
        return Response(serializer.data)

    serializer = TeacherInstrumentSerializer(
        data=request.data, context={'profile': profile}
    )
    if serializer.is_valid():
        serializer.save(profile=profile)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT', 'DELETE'])
@teacher_or_management_required
def teacher_instrument_detail(request, teacher_id, instrument_id):
    profile, error = _resolve_profile(request, teacher_id)
    if error:
        return error

    instrument = TeacherInstrument.objects.filter(
        pk=instrument_id, profile=profile
    ).first()
    if instrument is None:
        return Response(
            {'error': 'Instrument not found'}, status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'DELETE':
        instrument.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = TeacherInstrumentSerializer(
        instrument, data=request.data, partial=True, context={'profile': profile}
    )
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
@teacher_or_management_required
def teacher_availability_list(request, teacher_id):
    profile, error = _resolve_profile(request, teacher_id)
    if error:
        return error

    if request.method == 'GET':
        serializer = TeacherAvailabilitySerializer(
            profile.availability_slots.all(), many=True
        )
        return Response(serializer.data)

    serializer = TeacherAvailabilitySerializer(
        data=request.data, context={'profile': profile}
    )
    if serializer.is_valid():
        serializer.save(profile=profile)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT', 'DELETE'])
@teacher_or_management_required
def teacher_availability_detail(request, teacher_id, slot_id):
    profile, error = _resolve_profile(request, teacher_id)
    if error:
        return error

    slot = TeacherAvailability.objects.filter(pk=slot_id, profile=profile).first()
    if slot is None:
        return Response(
            {'error': 'Availability slot not found'}, status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'DELETE':
        slot.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = TeacherAvailabilitySerializer(
        slot, data=request.data, partial=True, context={'profile': profile}
    )
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
