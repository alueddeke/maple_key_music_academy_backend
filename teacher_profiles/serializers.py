from rest_framework import serializers

from .models import (
    SchoolInstrument,
    TeacherAvailability,
    TeacherInstrument,
    TeacherProfile,
)


class TeacherInstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherInstrument
        fields = [
            'id',
            'instrument',
            'skill_ceiling',
            'rate',
            'teaches_theory',
            'teaches_history',
            'teaches_rcm_prep',
        ]

    def validate_instrument(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Instrument name cannot be blank.")
        return value

    def validate_rate(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Rate cannot be negative.")
        return value

    def validate(self, attrs):
        # Case-insensitive uniqueness per profile (DB constraint is case-sensitive)
        profile = self.context.get('profile') or getattr(self.instance, 'profile', None)
        instrument = attrs.get('instrument') or getattr(self.instance, 'instrument', None)
        if profile and instrument:
            qs = TeacherInstrument.objects.filter(
                profile=profile, instrument__iexact=instrument
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {'instrument': 'This instrument is already on the profile.'}
                )
        return attrs


class TeacherAvailabilitySerializer(serializers.ModelSerializer):
    day_of_week_display = serializers.CharField(
        source='get_day_of_week_display', read_only=True
    )

    class Meta:
        model = TeacherAvailability
        fields = [
            'id',
            'day_of_week',
            'day_of_week_display',
            'start_time',
            'end_time',
        ]

    def validate(self, attrs):
        start = attrs.get('start_time') or getattr(self.instance, 'start_time', None)
        end = attrs.get('end_time') or getattr(self.instance, 'end_time', None)
        day = attrs.get('day_of_week')
        if day is None and self.instance:
            day = self.instance.day_of_week

        if start and end and end <= start:
            raise serializers.ValidationError(
                {'end_time': 'End time must be after start time.'}
            )

        # Reject overlapping windows on the same day for the same profile
        profile = self.context.get('profile') or getattr(self.instance, 'profile', None)
        if profile and day is not None and start and end:
            qs = TeacherAvailability.objects.filter(
                profile=profile,
                day_of_week=day,
                start_time__lt=end,
                end_time__gt=start,
            )
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {'start_time': 'This window overlaps an existing availability slot on that day.'}
                )
        return attrs


class TeacherProfileSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)
    teacher_email = serializers.EmailField(source='teacher.email', read_only=True)
    instruments = TeacherInstrumentSerializer(many=True, read_only=True)
    availability = TeacherAvailabilitySerializer(
        source='availability_slots', many=True, read_only=True
    )

    class Meta:
        model = TeacherProfile
        fields = [
            'id',
            'teacher',
            'teacher_name',
            'teacher_email',
            'notes',
            'teachable_area',
            'lat',
            'lng',
            'instruments',
            'availability',
            'updated_at',
        ]
        read_only_fields = ['id', 'teacher', 'updated_at']


class SchoolInstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolInstrument
        fields = ['id', 'name']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Instrument name cannot be blank.")
        return value

    def validate(self, attrs):
        # Case-insensitive uniqueness per school (DB constraint is case-sensitive)
        school = self.context.get('school') or getattr(self.instance, 'school', None)
        name = attrs.get('name') or getattr(self.instance, 'name', None)
        if school and name:
            qs = SchoolInstrument.objects.filter(school=school, name__iexact=name)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {'name': 'This instrument is already on the list.'}
                )
        return attrs
