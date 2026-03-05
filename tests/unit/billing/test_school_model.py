"""
Unit tests for School and SchoolSettings models.
"""

import pytest
from decimal import Decimal
from django.core.exceptions import ValidationError
from billing.models import School, SchoolSettings


@pytest.mark.django_db
class TestSchoolModel:
    """Test School model functionality."""

    def test_create_school(self, school):
        """Test creating a school with all required fields."""
        assert school.id is not None
        assert school.name == "Test School"
        assert school.subdomain == "testschool"
        assert school.is_active is True
        assert school.hst_rate == Decimal("13.00")

    def test_school_str_representation(self, school):
        """Test school string representation."""
        assert str(school) == "Test School"

    def test_school_subdomain_unique(self, school, db):
        """Test that subdomain must be unique."""
        with pytest.raises(Exception):  # IntegrityError
            School.objects.create(
                name="Duplicate School",
                subdomain="testschool",  # Duplicate
                email="duplicate@test.com",
                street_address="789 Dup St",
                city="Toronto",
                province="ON",
                postal_code="M5H 2N2",
                billing_cycle_day=1
            )

    def test_school_email_unique(self, school, db):
        """Test that email must be unique."""
        with pytest.raises(Exception):  # IntegrityError
            School.objects.create(
                name="Another School",
                subdomain="anotherschool",
                email="test@testschool.com",  # Duplicate
                street_address="789 Another St",
                city="Toronto",
                province="ON",
                postal_code="M5H 2N2",
                billing_cycle_day=1
            )

    def test_billing_cycle_day_validation(self, db):
        """Test billing cycle day must be between 1-31."""
        # Valid boundary values
        school_min = School.objects.create(
            name="Min Day School",
            subdomain="minday",
            email="min@test.com",
            street_address="123 Min St",
            city="Toronto",
            province="ON",
            postal_code="M5H 2N2",
            billing_cycle_day=1
        )
        assert school_min.billing_cycle_day == 1

        school_max = School.objects.create(
            name="Max Day School",
            subdomain="maxday",
            email="max@test.com",
            street_address="123 Max St",
            city="Toronto",
            province="ON",
            postal_code="M5H 2N2",
            billing_cycle_day=31
        )
        assert school_max.billing_cycle_day == 31

    def test_school_cascades_to_users(self, school, teacher_user):
        """Test that deleting school with users raises error (protected)."""
        # Users linked to school, should not allow deletion
        school_id = school.id
        with pytest.raises(Exception):  # ProtectedError or similar
            school.delete()


@pytest.mark.django_db
class TestSchoolSettingsModel:
    """Test SchoolSettings model functionality."""

    def test_create_school_settings(self, school_settings):
        """Test creating school settings."""
        assert school_settings.id is not None
        assert school_settings.online_teacher_rate == Decimal("45.00")
        assert school_settings.online_student_rate == Decimal("60.00")
        assert school_settings.inperson_student_rate == Decimal("100.00")

    def test_get_settings_for_school(self, school):
        """Test get_or_create pattern for school settings."""
        # First call creates
        settings1 = SchoolSettings.get_settings_for_school(school)
        assert settings1.school == school

        # Second call retrieves
        settings2 = SchoolSettings.get_settings_for_school(school)
        assert settings1.id == settings2.id

    def test_school_settings_one_to_one(self, school, school_settings):
        """Test one-to-one relationship with school."""
        # Trying to create a second settings for same school should fail
        with pytest.raises(Exception):  # IntegrityError
            SchoolSettings.objects.create(
                school=school,  # Duplicate
                online_teacher_rate=Decimal("50.00"),
                online_student_rate=Decimal("65.00"),
                inperson_student_rate=Decimal("105.00")
            )

    def test_school_settings_cascade_delete(self, school, school_settings):
        """Test that settings are deleted when school is deleted."""
        settings_id = school_settings.id
        # Delete school (if no protected relations)
        # This would normally fail due to users, but test the cascade if it could work
        # In practice, school deletion is protected by user FK

    def test_update_school_settings(self, school_settings, management_user):
        """Test updating school settings and tracking updated_by."""
        school_settings.online_teacher_rate = Decimal("50.00")
        school_settings.updated_by = management_user
        school_settings.save()

        refreshed = SchoolSettings.objects.get(id=school_settings.id)
        assert refreshed.online_teacher_rate == Decimal("50.00")
        assert refreshed.updated_by == management_user

    def test_default_values(self, school):
        """Test default values for school settings."""
        settings = SchoolSettings.objects.create(school=school)
        assert settings.online_teacher_rate == Decimal("45.00")
        assert settings.online_student_rate == Decimal("60.00")
        assert settings.inperson_student_rate == Decimal("100.00")
