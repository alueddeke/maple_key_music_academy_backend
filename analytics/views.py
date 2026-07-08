from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from billing.models import RecurringLessonsSchedule, SchoolExpenseItem
from custom_auth.decorators import management_required

from .models import ExpenseItemCategory, MetricGoal, ScheduleInstrument
from .serializers import (
    MetricGoalSerializer,
    ScheduleInstrumentSerializer,
    StudentExitRecordSerializer,
)
from .services import compute_overview

User = get_user_model()

MAX_MONTHS = 24


@api_view(['GET'])
@management_required
def analytics_overview(request):
    """All dashboard analytics: monthly trend rows + current metrics + goals."""
    try:
        months = int(request.query_params.get('months', 6))
    except (TypeError, ValueError):
        return Response(
            {'error': 'months must be an integer'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    months = max(1, min(months, MAX_MONTHS))
    return Response(compute_overview(request.user.school, months=months))


@api_view(['GET', 'PUT'])
@management_required
def metric_goals(request):
    """GET current goals; PUT replaces the full goal list for the school."""
    school = request.user.school

    if request.method == 'GET':
        goals = MetricGoal.objects.filter(school=school).order_by('metric')
        return Response(MetricGoalSerializer(goals, many=True).data)

    if not isinstance(request.data, list):
        return Response(
            {'error': 'Expected a list of {metric, target} objects'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = MetricGoalSerializer(data=request.data, many=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    seen_metrics = set()
    for item in serializer.validated_data:
        MetricGoal.objects.update_or_create(
            school=school,
            metric=item['metric'],
            defaults={'target': item['target'], 'updated_by': request.user},
        )
        seen_metrics.add(item['metric'])
    MetricGoal.objects.filter(school=school).exclude(
        metric__in=seen_metrics
    ).delete()

    goals = MetricGoal.objects.filter(school=school).order_by('metric')
    return Response(MetricGoalSerializer(goals, many=True).data)


@api_view(['GET'])
@management_required
def schedule_instrument_list(request):
    """Instrument tags, optionally filtered by student, for the user's school."""
    tags = ScheduleInstrument.objects.filter(
        schedule__school=request.user.school
    ).select_related('schedule')
    student_id = request.query_params.get('student_id')
    if student_id:
        tags = tags.filter(schedule__student_id=student_id)
    return Response(ScheduleInstrumentSerializer(tags, many=True).data)


@api_view(['PUT'])
@management_required
def schedule_instrument_detail(request, schedule_id):
    """Set (or clear, with empty instrument) the instrument tag for a schedule."""
    schedule = RecurringLessonsSchedule.objects.filter(
        pk=schedule_id, school=request.user.school
    ).first()
    if schedule is None:
        return Response(
            {'error': 'Schedule not found'}, status=status.HTTP_404_NOT_FOUND
        )

    instrument = (request.data.get('instrument') or '').strip()
    if not instrument:
        ScheduleInstrument.objects.filter(schedule=schedule).delete()
        return Response({'schedule_id': schedule.id, 'instrument': ''})

    tag, _ = ScheduleInstrument.objects.update_or_create(
        schedule=schedule, defaults={'instrument': instrument}
    )
    return Response(ScheduleInstrumentSerializer(tag).data)


@api_view(['PUT'])
@management_required
def expense_item_category(request, expense_item_id):
    """Set (or clear, with empty category) the category tag for an expense item."""
    item = SchoolExpenseItem.objects.filter(
        pk=expense_item_id, school=request.user.school
    ).first()
    if item is None:
        return Response(
            {'error': 'Expense item not found'}, status=status.HTTP_404_NOT_FOUND
        )

    category = (request.data.get('category') or '').strip()
    if not category:
        ExpenseItemCategory.objects.filter(expense_item=item).delete()
        return Response({'expense_item_id': item.id, 'category': ''})

    valid = {c for c, _ in ExpenseItemCategory.CATEGORY_CHOICES}
    if category not in valid:
        return Response(
            {'error': f'Invalid category. Choices: {sorted(valid)}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    ExpenseItemCategory.objects.update_or_create(
        expense_item=item, defaults={'category': category}
    )
    return Response({'expense_item_id': item.id, 'category': category})


@api_view(['POST'])
@management_required
def create_exit_record(request):
    """Record why a student left (called right after deactivation)."""
    student = User.objects.filter(
        pk=request.data.get('student'),
        user_type='student',
        school=request.user.school,
    ).first()
    if student is None:
        return Response(
            {'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND
        )

    serializer = StudentExitRecordSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(
            student=student,
            school=student.school,
            recorded_by=request.user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
