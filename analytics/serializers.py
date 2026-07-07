from rest_framework import serializers

from .models import MetricGoal, ScheduleInstrument, StudentExitRecord


class MetricGoalSerializer(serializers.ModelSerializer):
    metric_display = serializers.CharField(source='get_metric_display', read_only=True)

    class Meta:
        model = MetricGoal
        fields = ['metric', 'metric_display', 'target', 'updated_at']
        read_only_fields = ['updated_at']


class ScheduleInstrumentSerializer(serializers.ModelSerializer):
    schedule_id = serializers.IntegerField(source='schedule.id', read_only=True)

    class Meta:
        model = ScheduleInstrument
        fields = ['schedule_id', 'instrument']

    def validate_instrument(self, value):
        return value.strip()


class StudentExitRecordSerializer(serializers.ModelSerializer):
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)

    class Meta:
        model = StudentExitRecord
        fields = ['id', 'student', 'reason', 'reason_display', 'notes', 'created_at']
        read_only_fields = ['id', 'created_at']
