"""
Integration tests for independent school settings.

These tests verify that:
- Each school can have independent rate settings
- Updating one school's settings doesn't affect another
- Lessons use correct school-specific rates
"""

import pytest
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth import get_user_model
from billing.models import School, SchoolSettings, Lesson

User = get_user_model()


@pytest.mark.django_db
class TestIndependentSchoolSettings:
    """Test that each school has independent settings."""

    @pytest.fixture
    def school1_teacher(self, school, db):
        """Teacher from school 1."""
        return User.objects.create_user(
            email="teacher1@school1.com",
            password="test123",
            user_type="teacher",
            school=school,
            hourly_rate=Decimal("80.00"),
            is_approved=True
        )

    @pytest.fixture
    def school1_student(self, school, school1_teacher, db):
        """Student from school 1 with completed lesson to avoid trial auto-detection."""
        from decimal import Decimal

        student = User.objects.create_user(
            email="student1@school1.com",
            password="test123",
            user_type="student",
            school=school,
            is_approved=True
        )

        # Create completed lesson to avoid trial auto-detection
        Lesson.objects.create(
            teacher=school1_teacher,
            student=student,
            school=school,
            lesson_type='online',
            is_trial=True,
            teacher_rate=Decimal("45.00"),
            student_rate=Decimal("0.00"),
            scheduled_date=timezone.now() - timezone.timedelta(days=30),
            duration=1.0,
            status='completed'
        )

        return student

    @pytest.fixture
    def school2_teacher(self, second_school, db):
        """Teacher from school 2."""
        return User.objects.create_user(
            email="teacher2@school2.com",
            password="test123",
            user_type="teacher",
            school=second_school,
            hourly_rate=Decimal("75.00"),
            is_approved=True
        )

    @pytest.fixture
    def school2_student(self, second_school, school2_teacher, db):
        """Student from school 2 with completed lesson to avoid trial auto-detection."""
        from decimal import Decimal

        student = User.objects.create_user(
            email="student2@school2.com",
            password="test123",
            user_type="student",
            school=second_school,
            is_approved=True
        )

        # Create completed lesson to avoid trial auto-detection
        Lesson.objects.create(
            teacher=school2_teacher,
            student=student,
            school=second_school,
            lesson_type='online',
            is_trial=True,
            teacher_rate=Decimal("40.00"),
            student_rate=Decimal("0.00"),
            scheduled_date=timezone.now() - timezone.timedelta(days=30),
            duration=1.0,
            status='completed'
        )

        return student

    def test_schools_have_independent_settings(
        self, school, school_settings, second_school, second_school_settings
    ):
        """Test that each school has its own settings instance."""
        assert school_settings.school == school
        assert second_school_settings.school == second_school
        assert school_settings.id != second_school_settings.id

    def test_schools_can_have_different_rates(
        self, school_settings, second_school_settings
    ):
        """Test that schools can have different rate configurations."""
        # School 1 rates
        assert school_settings.online_teacher_rate == Decimal("45.00")
        assert school_settings.online_student_rate == Decimal("60.00")
        assert school_settings.inperson_student_rate == Decimal("100.00")

        # School 2 rates (different)
        assert second_school_settings.online_teacher_rate == Decimal("40.00")
        assert second_school_settings.online_student_rate == Decimal("55.00")
        assert second_school_settings.inperson_student_rate == Decimal("90.00")

    def test_updating_one_school_settings_doesnt_affect_another(
        self, school_settings, second_school_settings
    ):
        """Test that updating school 1 settings doesn't change school 2."""
        # Record original school 2 rates
        original_school2_online_teacher = second_school_settings.online_teacher_rate
        original_school2_online_student = second_school_settings.online_student_rate

        # Update school 1 settings
        school_settings.online_teacher_rate = Decimal("50.00")
        school_settings.online_student_rate = Decimal("65.00")
        school_settings.save()

        # Refresh school 2 settings
        second_school_settings.refresh_from_db()

        # Verify school 2 settings unchanged
        assert second_school_settings.online_teacher_rate == original_school2_online_teacher
        assert second_school_settings.online_student_rate == original_school2_online_student

    def test_lessons_use_correct_school_rates(
        self, school, school_settings, second_school, second_school_settings,
        school1_teacher, school1_student, school2_teacher, school2_student
    ):
        """Test that lessons use their school's specific rates."""
        # Create lesson in school 1
        lesson1 = Lesson.objects.create(
            teacher=school1_teacher,
            student=school1_student,
            school=school,
            lesson_type='online',
            is_trial=False,  # Explicitly not a trial
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Create lesson in school 2
        lesson2 = Lesson.objects.create(
            teacher=school2_teacher,
            student=school2_student,
            school=second_school,
            lesson_type='online',
            is_trial=False,  # Explicitly not a trial
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Verify each lesson uses its school's rates
        assert lesson1.teacher_rate == school_settings.online_teacher_rate
        assert lesson1.student_rate == school_settings.online_student_rate
        assert lesson2.teacher_rate == second_school_settings.online_teacher_rate
        assert lesson2.student_rate == second_school_settings.online_student_rate

        # Explicitly verify they're different
        assert lesson1.teacher_rate != lesson2.teacher_rate
        assert lesson1.student_rate != lesson2.student_rate

    def test_get_settings_for_school_returns_correct_instance(
        self, school, school_settings, second_school, second_school_settings
    ):
        """Test that get_settings_for_school returns the correct instance."""
        retrieved1 = SchoolSettings.get_settings_for_school(school)
        assert retrieved1.id == school_settings.id
        assert retrieved1.school == school

        retrieved2 = SchoolSettings.get_settings_for_school(second_school)
        assert retrieved2.id == second_school_settings.id
        assert retrieved2.school == second_school

    def test_inperson_lessons_use_correct_school_rates(
        self, school, school_settings, second_school, second_school_settings,
        school1_teacher, school1_student, school2_teacher, school2_student
    ):
        """Test that in-person lessons use correct school rates."""
        # Create in-person lesson in school 1
        lesson1 = Lesson.objects.create(
            teacher=school1_teacher,
            student=school1_student,
            school=school,
            lesson_type='in_person',
            is_trial=False,  # Explicitly not a trial
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Create in-person lesson in school 2
        lesson2 = Lesson.objects.create(
            teacher=school2_teacher,
            student=school2_student,
            school=second_school,
            lesson_type='in_person',
            is_trial=False,  # Explicitly not a trial
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Verify teacher rates use their hourly_rate
        assert lesson1.teacher_rate == school1_teacher.hourly_rate
        assert lesson2.teacher_rate == school2_teacher.hourly_rate

        # Verify student rates use school-specific in-person rates
        assert lesson1.student_rate == school_settings.inperson_student_rate
        assert lesson2.student_rate == second_school_settings.inperson_student_rate
        assert lesson1.student_rate != lesson2.student_rate  # Different schools

    def test_rate_independence_after_multiple_updates(
        self, school_settings, second_school_settings
    ):
        """Test that settings remain independent after multiple updates."""
        # Multiple updates to school 1
        school_settings.online_teacher_rate = Decimal("48.00")
        school_settings.save()
        school_settings.online_student_rate = Decimal("62.00")
        school_settings.save()

        # Multiple updates to school 2
        second_school_settings.online_teacher_rate = Decimal("42.00")
        second_school_settings.save()
        second_school_settings.online_student_rate = Decimal("57.00")
        second_school_settings.save()

        # Refresh both
        school_settings.refresh_from_db()
        second_school_settings.refresh_from_db()

        # Verify each has its own values
        assert school_settings.online_teacher_rate == Decimal("48.00")
        assert school_settings.online_student_rate == Decimal("62.00")
        assert second_school_settings.online_teacher_rate == Decimal("42.00")
        assert second_school_settings.online_student_rate == Decimal("57.00")

    def test_trial_lessons_use_school_context(
        self, school, school_settings, second_school, second_school_settings,
        school1_teacher, school1_student, school2_teacher, school2_student
    ):
        """Test that trial lessons use correct school for teacher rate."""
        # Trial lesson in school 1
        trial1 = Lesson.objects.create(
            teacher=school1_teacher,
            student=school1_student,
            school=school,
            lesson_type='online',
            is_trial=True,
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Trial lesson in school 2
        trial2 = Lesson.objects.create(
            teacher=school2_teacher,
            student=school2_student,
            school=second_school,
            lesson_type='online',
            is_trial=True,
            scheduled_date=timezone.now(),
            duration=1.0,
            status='confirmed'
        )

        # Both should have student_rate = 0
        assert trial1.student_rate == Decimal("0.00")
        assert trial2.student_rate == Decimal("0.00")

        # But teacher rates should use respective school rates
        assert trial1.teacher_rate == school_settings.online_teacher_rate
        assert trial2.teacher_rate == second_school_settings.online_teacher_rate
        assert trial1.teacher_rate != trial2.teacher_rate  # Different schools
