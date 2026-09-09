"""
MAP-177: migration 0070_demote_non_platform_admins.

pytest runs with --no-migrations, so the migration module is imported with
importlib and its module-level forward()/reverse() are called against the
live app registry. Assertions are on User rows, never on SQL.
"""
import importlib

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

User = get_user_model()
migration = importlib.import_module('billing.migrations.0070_demote_non_platform_admins')

OWNER = 'owner@platform.test'


def _user(email, user_type, school, *, staff):
    user = User.objects.create_user(
        email=email, password='x', user_type=user_type, school=school,
        first_name='F', last_name='L', is_approved=True,
    )
    # Reproduce today's production state (flags derived from user_type, or tampered)
    # without going through save().
    User.objects.filter(pk=user.pk).update(is_staff=staff, is_superuser=staff)
    user.refresh_from_db()
    return user


def _flags(user):
    user.refresh_from_db()
    return (user.is_staff, user.is_superuser)


@pytest.fixture
def three_users(school):
    owner = _user(OWNER, 'management', school, staff=True)
    manager = _user('manager@school.test', 'management', school, staff=True)
    student = _user('student@school.test', 'student', school, staff=True)  # tampered
    return owner, manager, student


@pytest.mark.django_db
class TestDemoteMigration:

    def test_forward_keeps_only_allowlisted_flags(self, three_users):
        owner, manager, student = three_users

        with override_settings(PLATFORM_ADMIN_EMAILS=[OWNER]):
            migration.forward(django_apps, None)

        assert _flags(owner) == (True, True)
        assert _flags(manager) == (False, False)
        assert _flags(student) == (False, False)

    def test_reverse_restores_management_derivation(self, three_users):
        owner, manager, student = three_users
        with override_settings(PLATFORM_ADMIN_EMAILS=[OWNER]):
            migration.forward(django_apps, None)

        migration.reverse(django_apps, None)

        assert _flags(owner) == (True, True)
        assert _flags(manager) == (True, True)
        assert _flags(student) == (False, False)

    def test_forward_empty_allowlist_raises_and_changes_nothing(self, three_users):
        owner, manager, student = three_users

        with override_settings(PLATFORM_ADMIN_EMAILS=[]):
            with pytest.raises(ImproperlyConfigured):
                migration.forward(django_apps, None)

        assert _flags(owner) == (True, True)
        assert _flags(manager) == (True, True)
        assert _flags(student) == (True, True)

    def test_forward_empty_user_table_returns_without_raising(self):
        assert not User.objects.exists()

        with override_settings(PLATFORM_ADMIN_EMAILS=[OWNER]):
            migration.forward(django_apps, None)

        assert not User.objects.exists()

    def test_forward_allowlisted_email_without_row_raises_and_changes_nothing(self, three_users):
        owner, manager, student = three_users

        with override_settings(PLATFORM_ADMIN_EMAILS=[OWNER, 'ghost@platform.test']):
            with pytest.raises(ImproperlyConfigured) as exc:
                migration.forward(django_apps, None)

        assert 'ghost@platform.test' in str(exc.value)
        assert _flags(manager) == (True, True)
        assert _flags(student) == (True, True)
