from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords


class TeacherProfile(models.Model):
    """Structured professional profile for a teacher.

    Extends the thin User teacher record (email + assignments) with the
    structured data needed for future lead-generation matching:
    instruments taught, weekly availability, teachable location, notes.

    # LEAD-GEN: consumes this — the lead-generation matching engine
    # (incoming student request → teacher availability/location match)
    # attaches here. Not built yet; needs matching rules from product.
    """
    teacher = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='teacher_profile',
        limit_choices_to={'user_type': 'teacher'},
    )
    school = models.ForeignKey(
        'billing.School',
        on_delete=models.PROTECT,
        related_name='teacher_profiles',
    )
    notes = models.TextField(
        blank=True,
        default='',
        help_text="Free-text notes about the teacher (visible to management and the teacher)",
    )
    teachable_area = models.TextField(
        blank=True,
        default='',
        help_text="Locations/areas where the teacher can teach (free text, e.g. neighbourhoods)",
    )
    lat = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        help_text="Optional latitude of the teacher's base location",
    )
    lng = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        help_text="Optional longitude of the teacher's base location",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        # School always mirrors the teacher's school (multi-tenancy convention)
        if not self.school_id and self.teacher_id:
            self.school = self.teacher.school
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Teacher profile: {self.teacher.get_full_name()} ({self.teacher.email})"


class TeacherInstrument(models.Model):
    """An instrument a teacher teaches, with skill ceiling and optional rate.

    `rate` is a per-instrument teaching rate (teacher config for matching).
    There is deliberately NO FK to an existing rate model: the codebase has
    no per-instrument rate source of truth — `User.hourly_rate` is a single
    flat teacher rate and `SchoolSettings` rates are per-school per-lesson-type.
    This field is teacher profile config only and is NOT consumed by any
    billing/charging logic.
    """
    SKILL_CEILING_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
    ]

    profile = models.ForeignKey(
        TeacherProfile,
        on_delete=models.CASCADE,
        related_name='instruments',
    )
    instrument = models.CharField(max_length=100)
    skill_ceiling = models.CharField(
        max_length=20,
        choices=SKILL_CEILING_CHOICES,
        help_text="Highest student level the teacher takes on this instrument",
    )
    rate = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Optional per-instrument hourly rate (teacher config, not billing)",
    )
    teaches_theory = models.BooleanField(default=False)
    teaches_history = models.BooleanField(default=False)
    teaches_rcm_prep = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ['instrument']
        constraints = [
            models.UniqueConstraint(
                fields=['profile', 'instrument'],
                name='unique_instrument_per_profile',
            ),
        ]

    def __str__(self):
        return (
            f"{self.profile.teacher.get_full_name()} — {self.instrument} "
            f"({self.get_skill_ceiling_display()})"
        )


class TeacherAvailability(models.Model):
    """A weekly recurring availability window for a teacher.

    day_of_week uses 0=Monday … 6=Sunday, matching the existing
    RecurringLessonsSchedule / frontend convention.
    """
    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    profile = models.ForeignKey(
        TeacherProfile,
        on_delete=models.CASCADE,
        related_name='availability_slots',
    )
    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ['day_of_week', 'start_time']
        verbose_name_plural = 'teacher availabilities'
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_time__gt=models.F('start_time')),
                name='availability_end_after_start',
            ),
        ]

    def __str__(self):
        return (
            f"{self.profile.teacher.get_full_name()} — {self.get_day_of_week_display()} "
            f"{self.start_time:%H:%M}–{self.end_time:%H:%M}"
        )


class SchoolInstrument(models.Model):
    """A management-curated instrument the school offers.

    Source of the instrument dropdowns on teacher profiles and student
    schedules — free-text entry caused typos and unapproved instruments.
    Management edits this list; teachers only pick from it.
    """
    school = models.ForeignKey(
        'billing.School',
        on_delete=models.CASCADE,
        related_name='school_instruments',
    )
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['school', 'name'],
                name='unique_instrument_per_school',
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.school})"
