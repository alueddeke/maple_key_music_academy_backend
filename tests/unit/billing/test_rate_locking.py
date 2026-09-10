"""
Unit tests to verify rate locking is preserved with school context.

Rate locking means:
- Lesson rates are set at creation time from school settings
- Once set, lesson rates NEVER change even if school settings are updated
- This preserves financial history accuracy
"""

import pytest
from decimal import Decimal
from django.utils import timezone
from billing.models import Lesson, SchoolSettings


@pytest.mark.django_db
class TestRateLocking:
    """Test that lesson rates are locked at creation and don't change."""

    def test_online_lesson_rates_locked_at_creation(
        self, school, school_settings, teacher_user, student_user
    ):
        """Test that online lesson rates are locked from school settings at creation."""
        # Create lesson with current school settings
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=school,
            lesson_type='online',
            is_trial=False,  # Explicitly not a trial
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Verify rates match school settings
        assert lesson.teacher_rate == school_settings.online_teacher_rate
        assert lesson.student_rate == school_settings.online_student_rate
        assert lesson.teacher_rate == Decimal("45.00")
        assert lesson.student_rate == Decimal("60.00")

        # Update school settings
        school_settings.online_teacher_rate = Decimal("50.00")
        school_settings.online_student_rate = Decimal("65.00")
        school_settings.save()

        # Refresh lesson from database
        lesson.refresh_from_db()

        # CRITICAL: Rates should NOT change
        assert lesson.teacher_rate == Decimal("45.00"), "Teacher rate changed - rate locking broken!"
        assert lesson.student_rate == Decimal("60.00"), "Student rate changed - rate locking broken!"

    def test_inperson_lesson_rates_locked_at_creation(
        self, school, school_settings, teacher_user, student_user
    ):
        """Test that in-person lesson rates are locked at creation."""
        # Create in-person lesson
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=school,
            lesson_type='in_person',
            is_trial=False,  # Explicitly not a trial
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Verify rates: teacher gets hourly_rate, student pays school rate
        assert lesson.teacher_rate == teacher_user.hourly_rate
        assert lesson.student_rate == school_settings.inperson_student_rate
        assert lesson.teacher_rate == Decimal("80.00")
        assert lesson.student_rate == Decimal("100.00")

        # Update both teacher hourly rate and school settings
        teacher_user.hourly_rate = Decimal("90.00")
        teacher_user.save()
        school_settings.inperson_student_rate = Decimal("110.00")
        school_settings.save()

        # Refresh lesson
        lesson.refresh_from_db()

        # CRITICAL: Rates should NOT change
        assert lesson.teacher_rate == Decimal("80.00"), "Teacher rate changed - rate locking broken!"
        assert lesson.student_rate == Decimal("100.00"), "Student rate changed - rate locking broken!"

    def test_trial_lesson_student_rate_locked_at_zero(
        self, school, school_settings, teacher_user, student_user
    ):
        """Test that trial lesson student rate is locked at $0 regardless of settings."""
        # Create trial lesson
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=school,
            lesson_type='online',
            is_trial=True,
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Verify trial lesson has $0 student rate
        assert lesson.student_rate == Decimal("0.00")
        assert lesson.teacher_rate == Decimal("45.00")  # Teacher still gets paid

        # Update school settings
        school_settings.online_student_rate = Decimal("100.00")
        school_settings.save()

        # Refresh lesson
        lesson.refresh_from_db()

        # CRITICAL: Trial lesson student rate stays $0
        assert lesson.student_rate == Decimal("0.00"), "Trial student rate changed!"

    def test_multiple_lessons_different_rate_periods(
        self, school, school_settings, teacher_user, student_user
    ):
        """Test that lessons created in different rate periods have correct locked rates."""
        # Create first lesson with original rates
        lesson1 = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=school,
            lesson_type='online',
            is_trial=False,  # Explicitly not a trial
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )
        lesson1_teacher_rate = lesson1.teacher_rate
        lesson1_student_rate = lesson1.student_rate

        # Change school rates
        school_settings.online_teacher_rate = Decimal("50.00")
        school_settings.online_student_rate = Decimal("65.00")
        school_settings.save()

        # Create second lesson with new rates
        lesson2 = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=school,
            lesson_type='online',
            is_trial=False,  # Explicitly not a trial
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Verify each lesson has rates from its creation time
        lesson1.refresh_from_db()
        assert lesson1.teacher_rate == lesson1_teacher_rate  # Original rate
        assert lesson1.student_rate == lesson1_student_rate  # Original rate
        assert lesson2.teacher_rate == Decimal("50.00")  # New rate
        assert lesson2.student_rate == Decimal("65.00")  # New rate

    def test_rate_locking_with_lesson_save_method(
        self, school, school_settings, teacher_user, student_user
    ):
        """Test that using Lesson.save() doesn't override locked rates."""
        # Create lesson
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=school,
            lesson_type='online',
            is_trial=False,  # Explicitly not a trial
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )
        original_teacher_rate = lesson.teacher_rate
        original_student_rate = lesson.student_rate

        # Change school settings
        school_settings.online_teacher_rate = Decimal("99.00")
        school_settings.online_student_rate = Decimal("199.00")
        school_settings.save()

        # Call save() on lesson (e.g., updating status)
        lesson.status = 'completed'
        lesson.save()

        # Verify rates didn't change
        assert lesson.teacher_rate == original_teacher_rate
        assert lesson.student_rate == original_student_rate

    def test_manual_rate_override_is_preserved(
        self, school, school_settings, teacher_user, student_user
    ):
        """Test that manually set rates are preserved (special pricing)."""
        # Create lesson with manually set rates (special discount)
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=school,
            lesson_type='online',
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed',
            teacher_rate=Decimal("40.00"),  # Manual override
            student_rate=Decimal("50.00")   # Manual override
        )

        # Verify manual rates are set
        assert lesson.teacher_rate == Decimal("40.00")
        assert lesson.student_rate == Decimal("50.00")

        # Update school settings
        school_settings.online_teacher_rate = Decimal("45.00")
        school_settings.online_student_rate = Decimal("60.00")
        school_settings.save()

        # Save lesson
        lesson.status = 'completed'
        lesson.save()

        # Manual rates should be preserved
        lesson.refresh_from_db()
        assert lesson.teacher_rate == Decimal("40.00")
        assert lesson.student_rate == Decimal("50.00")


# ---------------------------------------------------------------------------
# MAP-182: Lesson.save() / RecurringLessonsSchedule.save() resolve rates via
# billing.services.rates.resolve_rates when a rate is None; explicit rates are
# kept; trial -> student_rate 0; GlobalRateSettings is never consulted.
# Assertions compare against fixture values, never rate literals.
# ---------------------------------------------------------------------------

from datetime import date, time
from django.contrib.auth import get_user_model
from billing.models import GlobalRateSettings, RecurringLessonsSchedule

User = get_user_model()


@pytest.fixture
def second_teacher(second_school, teacher_user, db):
    return User.objects.create_user(
        email="teacher2@secondschool.com",
        password="testpass123",
        user_type="teacher",
        first_name="Second",
        last_name="Teacher",
        hourly_rate=teacher_user.hourly_rate + Decimal("7.00"),
        school=second_school,
        is_approved=True,
    )


@pytest.fixture
def second_student(second_school, second_teacher, db):
    """Student in the second school with a completed lesson so trial auto-detect stays off."""
    student = User.objects.create_user(
        email="student2@secondschool.com",
        password="testpass123",
        user_type="student",
        first_name="Second",
        last_name="Student",
        school=second_school,
        is_approved=True,
    )
    Lesson.objects.create(
        teacher=second_teacher,
        student=student,
        school=second_school,
        lesson_type='online',
        is_trial=True,
        teacher_rate=second_teacher.hourly_rate,
        student_rate=Decimal("0.00"),
        scheduled_date=timezone.now() - timezone.timedelta(days=30),
        duration=1.0,
        status='completed',
    )
    return student


def _lesson_kwargs(teacher, student, school, lesson_type, **extra):
    base = dict(
        teacher=teacher,
        student=student,
        school=school,
        lesson_type=lesson_type,
        is_trial=False,
        scheduled_date=timezone.now(),
        duration=1.0,
        status='confirmed',
    )
    base.update(extra)
    return base


@pytest.mark.django_db
class TestResolveWhenNone:

    def test_lessons_in_two_schools_resolve_from_own_settings_with_globals_deleted(
        self, school, school_settings, teacher_user, student_user,
        second_school, second_school_settings, second_teacher, second_student,
    ):
        GlobalRateSettings.objects.all().delete()

        online1 = Lesson.objects.create(**_lesson_kwargs(teacher_user, student_user, school, 'online'))
        inperson1 = Lesson.objects.create(**_lesson_kwargs(teacher_user, student_user, school, 'in_person'))
        online2 = Lesson.objects.create(**_lesson_kwargs(second_teacher, second_student, second_school, 'online'))
        inperson2 = Lesson.objects.create(**_lesson_kwargs(second_teacher, second_student, second_school, 'in_person'))

        for lesson in (online1, inperson1, online2, inperson2):
            lesson.refresh_from_db()

        assert (online1.teacher_rate, online1.student_rate) == (
            school_settings.online_teacher_rate, school_settings.online_student_rate)
        assert (inperson1.teacher_rate, inperson1.student_rate) == (
            teacher_user.hourly_rate, school_settings.inperson_student_rate)
        assert (online2.teacher_rate, online2.student_rate) == (
            second_school_settings.online_teacher_rate, second_school_settings.online_student_rate)
        assert (inperson2.teacher_rate, inperson2.student_rate) == (
            second_teacher.hourly_rate, second_school_settings.inperson_student_rate)

        assert (online1.teacher_rate, online1.student_rate) != (online2.teacher_rate, online2.student_rate)
        assert (inperson1.teacher_rate, inperson1.student_rate) != (inperson2.teacher_rate, inperson2.student_rate)
        assert GlobalRateSettings.objects.count() == 0

    def test_lesson_without_rates_resolves_in_person_from_teacher_and_school(
        self, school, school_settings, teacher_user, student_user
    ):
        teacher_user.hourly_rate = school_settings.inperson_student_rate + Decimal("11.00")
        teacher_user.save()

        lesson = Lesson.objects.create(**_lesson_kwargs(teacher_user, student_user, school, 'in_person'))
        lesson.refresh_from_db()

        assert lesson.teacher_rate == teacher_user.hourly_rate
        assert lesson.student_rate == school_settings.inperson_student_rate

    def test_lesson_with_explicit_rates_keeps_them(
        self, school, school_settings, teacher_user, student_user
    ):
        explicit_teacher = school_settings.online_teacher_rate + Decimal("5.00")
        explicit_student = school_settings.online_student_rate + Decimal("5.00")

        lesson = Lesson.objects.create(**_lesson_kwargs(
            teacher_user, student_user, school, 'online',
            teacher_rate=explicit_teacher, student_rate=explicit_student,
        ))
        lesson.refresh_from_db()

        assert lesson.teacher_rate == explicit_teacher
        assert lesson.student_rate == explicit_student
        assert lesson.teacher_rate != school_settings.online_teacher_rate
        assert lesson.student_rate != school_settings.online_student_rate

    def test_lesson_with_one_rate_missing_resolves_both(
        self, school, school_settings, teacher_user, student_user
    ):
        partial = school_settings.online_teacher_rate + Decimal("5.00")

        lesson = Lesson.objects.create(**_lesson_kwargs(
            teacher_user, student_user, school, 'online', teacher_rate=partial,
        ))
        lesson.refresh_from_db()

        assert lesson.teacher_rate == school_settings.online_teacher_rate
        assert lesson.student_rate == school_settings.online_student_rate

    def test_trial_lesson_student_rate_zero_teacher_rate_resolved(
        self, school, school_settings, teacher_user, student_user
    ):
        lesson = Lesson.objects.create(**_lesson_kwargs(
            teacher_user, student_user, school, 'in_person', is_trial=True,
        ))
        lesson.refresh_from_db()

        assert lesson.student_rate == Decimal("0.00")
        assert lesson.teacher_rate == teacher_user.hourly_rate

    def test_marking_existing_lesson_trial_zeroes_student_rate(
        self, school, school_settings, teacher_user, student_user
    ):
        lesson = Lesson.objects.create(**_lesson_kwargs(teacher_user, student_user, school, 'online'))
        assert lesson.student_rate == school_settings.online_student_rate

        lesson.is_trial = True
        lesson.save()
        lesson.refresh_from_db()

        assert lesson.student_rate == Decimal("0.00")
        assert lesson.teacher_rate == school_settings.online_teacher_rate

    def test_schedules_in_two_schools_resolve_from_own_settings(
        self, school, school_settings, teacher_user, student_user,
        second_school, second_school_settings, second_teacher, second_student,
    ):
        GlobalRateSettings.objects.all().delete()

        def make(teacher, student, school_, lesson_type, day):
            return RecurringLessonsSchedule.objects.create(
                teacher=teacher, student=student, school=school_,
                day_of_week=day, start_time=time(15, 0), duration=Decimal("1.0"),
                lesson_type=lesson_type, start_date=date(2026, 1, 1),
            )

        online1 = make(teacher_user, student_user, school, 'online', 0)
        inperson1 = make(teacher_user, student_user, school, 'in_person', 1)
        online2 = make(second_teacher, second_student, second_school, 'online', 0)
        inperson2 = make(second_teacher, second_student, second_school, 'in_person', 1)

        for sched in (online1, inperson1, online2, inperson2):
            sched.refresh_from_db()

        assert (online1.teacher_rate, online1.student_rate) == (
            school_settings.online_teacher_rate, school_settings.online_student_rate)
        assert (inperson1.teacher_rate, inperson1.student_rate) == (
            teacher_user.hourly_rate, school_settings.inperson_student_rate)
        assert (online2.teacher_rate, online2.student_rate) == (
            second_school_settings.online_teacher_rate, second_school_settings.online_student_rate)
        assert (inperson2.teacher_rate, inperson2.student_rate) == (
            second_teacher.hourly_rate, second_school_settings.inperson_student_rate)
        assert GlobalRateSettings.objects.count() == 0

    def test_schedule_with_explicit_rates_keeps_them(
        self, school, school_settings, teacher_user, student_user
    ):
        explicit_teacher = teacher_user.hourly_rate + Decimal("9.00")
        explicit_student = school_settings.inperson_student_rate + Decimal("9.00")

        sched = RecurringLessonsSchedule.objects.create(
            teacher=teacher_user, student=student_user, school=school,
            day_of_week=2, start_time=time(16, 0), duration=Decimal("1.0"),
            lesson_type='in_person', start_date=date(2026, 1, 1),
            teacher_rate=explicit_teacher, student_rate=explicit_student,
        )
        sched.refresh_from_db()

        assert sched.teacher_rate == explicit_teacher
        assert sched.student_rate == explicit_student
