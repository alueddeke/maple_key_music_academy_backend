"""
Unit tests for billing.services.rates.resolve_rates (MAP-182).

One function resolves rates. Precedence:
  in_person -> (teacher.hourly_rate, school_settings.inperson_student_rate)
  online    -> (school_settings.online_teacher_rate, school_settings.online_student_rate)

SchoolSettings.get_settings_for_school(school) is the only settings source;
GlobalRateSettings is never read. Assertions compare against fixture values,
never rate literals.
"""

import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model

from billing.models import GlobalRateSettings, SchoolSettings
from billing.services.rates import resolve_rates

User = get_user_model()


@pytest.fixture
def second_teacher(second_school, teacher_user, db):
    """Teacher in the second school with an hourly_rate distinct from teacher_user's."""
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


@pytest.mark.django_db
class TestResolveRates:

    def test_online_rates_come_from_own_school_settings(
        self, school, school_settings, second_school, second_school_settings,
        teacher_user, second_teacher,
    ):
        first = resolve_rates(school, teacher_user, 'online')
        second = resolve_rates(second_school, second_teacher, 'online')

        assert first == (
            school_settings.online_teacher_rate,
            school_settings.online_student_rate,
        )
        assert second == (
            second_school_settings.online_teacher_rate,
            second_school_settings.online_student_rate,
        )
        assert first != second

    def test_in_person_rates_use_teacher_hourly_rate_and_own_school_student_rate(
        self, school, school_settings, second_school, second_school_settings,
        teacher_user, second_teacher,
    ):
        first = resolve_rates(school, teacher_user, 'in_person')
        second = resolve_rates(second_school, second_teacher, 'in_person')

        assert first == (teacher_user.hourly_rate, school_settings.inperson_student_rate)
        assert second == (second_teacher.hourly_rate, second_school_settings.inperson_student_rate)
        assert first != second

    @pytest.mark.parametrize(
        "hourly_rate",
        [Decimal("0.00"), Decimal("12.34"), Decimal("250.00")],
    )
    def test_in_person_teacher_rate_follows_hourly_rate_as_stored(
        self, school, school_settings, teacher_user, hourly_rate
    ):
        teacher_user.hourly_rate = hourly_rate
        teacher_user.save()

        teacher_rate, student_rate = resolve_rates(school, teacher_user, 'in_person')

        assert teacher_rate == teacher_user.hourly_rate
        assert student_rate == school_settings.inperson_student_rate

    def test_online_rates_ignore_teacher_hourly_rate(
        self, school, school_settings, teacher_user
    ):
        before = resolve_rates(school, teacher_user, 'online')

        teacher_user.hourly_rate = teacher_user.hourly_rate + Decimal("25.00")
        teacher_user.save()

        after = resolve_rates(school, teacher_user, 'online')

        assert after == before
        assert after == (
            school_settings.online_teacher_rate,
            school_settings.online_student_rate,
        )

    def test_resolution_never_reads_global_rate_settings(
        self, school, school_settings, teacher_user
    ):
        GlobalRateSettings.objects.all().delete()
        assert GlobalRateSettings.objects.count() == 0

        online = resolve_rates(school, teacher_user, 'online')
        in_person = resolve_rates(school, teacher_user, 'in_person')

        assert online == (
            school_settings.online_teacher_rate,
            school_settings.online_student_rate,
        )
        assert in_person == (teacher_user.hourly_rate, school_settings.inperson_student_rate)
        # No get_or_create side effect on the legacy singleton.
        assert GlobalRateSettings.objects.count() == 0

    def test_school_without_settings_row_resolves_from_created_settings(
        self, school, teacher_user
    ):
        assert not SchoolSettings.objects.filter(school=school).exists()

        online = resolve_rates(school, teacher_user, 'online')
        in_person = resolve_rates(school, teacher_user, 'in_person')

        created = SchoolSettings.objects.get(school=school)
        assert online == (created.online_teacher_rate, created.online_student_rate)
        assert in_person == (teacher_user.hourly_rate, created.inperson_student_rate)
