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
