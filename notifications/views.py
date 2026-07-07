from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from custom_auth.decorators import teacher_or_management_required

from .models import Notification, NotificationPreference
from .serializers import NotificationPreferenceSerializer, NotificationSerializer

# Most recent notifications returned by the list endpoint (bell dropdown)
NOTIFICATION_LIST_LIMIT = 50


@api_view(['GET'])
@teacher_or_management_required
def notification_list(request):
    """The current user's latest notifications + unread count."""
    queryset = Notification.objects.filter(user=request.user)
    unread_count = queryset.filter(read_status=False).count()
    serializer = NotificationSerializer(queryset[:NOTIFICATION_LIST_LIMIT], many=True)
    return Response({
        'notifications': serializer.data,
        'unread_count': unread_count,
    })


@api_view(['POST'])
@teacher_or_management_required
def notification_mark_read(request, notification_id):
    notification = Notification.objects.filter(
        pk=notification_id, user=request.user
    ).first()
    if notification is None:
        return Response(
            {'error': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND
        )
    if not notification.read_status:
        notification.read_status = True
        notification.save(update_fields=['read_status'])
    return Response(NotificationSerializer(notification).data)


@api_view(['POST'])
@teacher_or_management_required
def notification_mark_all_read(request):
    updated = Notification.objects.filter(
        user=request.user, read_status=False
    ).update(read_status=True)
    return Response({'marked_read': updated})


@api_view(['GET', 'PUT'])
@teacher_or_management_required
def notification_preferences(request):
    """Get or update the current user's delivery opt-in preferences."""
    prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)

    if request.method == 'GET':
        return Response(NotificationPreferenceSerializer(prefs).data)

    serializer = NotificationPreferenceSerializer(
        prefs, data=request.data, partial=True
    )
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
