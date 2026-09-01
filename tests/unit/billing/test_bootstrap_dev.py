"""
Guard tests for bootstrap_dev (first-boot dev seeding).

The command runs on EVERY dev container boot — these tests pin the three
behaviors that make that safe: no-op when already seeded (never wipes working
data), refusal outside a dev environment, and DEV_SEED=off opt-out.
"""
from unittest import mock

import pytest
from django.core.management import call_command


pytestmark = pytest.mark.django_db


def _run(**env):
    with mock.patch.dict('os.environ', env, clear=False):
        with mock.patch(
            'billing.management.commands.bootstrap_dev.call_command'
        ) as inner:
            call_command('bootstrap_dev')
    return inner


def test_noops_when_sentinel_user_exists(django_user_model, school, settings):
    settings.DEBUG = True
    django_user_model.objects.create_user(
        email='e2e.manager@maplekeytest.com', password='testpass123',
        user_type='management', school=school, is_approved=True,
    )
    inner = _run(DEV_SEED='', DATABASE_URL='')
    inner.assert_not_called()


def test_refuses_outside_debug(settings):
    settings.DEBUG = False
    inner = _run(DEV_SEED='', DATABASE_URL='')
    inner.assert_not_called()


def test_runs_even_with_database_url_when_debug(settings, django_user_model):
    # Local dev connects through DATABASE_URL too — it must not block seeding.
    settings.DEBUG = True
    inner = _run(DEV_SEED='', DATABASE_URL='postgresql://db:5432/maple_key_dev')
    assert [c.args[0] for c in inner.call_args_list] == ['ensure_e2e_users', 'seed_realistic']


def test_dev_seed_off_skips(settings):
    settings.DEBUG = True
    inner = _run(DEV_SEED='off', DATABASE_URL='')
    inner.assert_not_called()


def test_seeds_empty_dev_database(settings):
    settings.DEBUG = True
    inner = _run(DEV_SEED='', DATABASE_URL='')
    called = [c.args[0] for c in inner.call_args_list]
    assert called == ['ensure_e2e_users', 'seed_realistic']
