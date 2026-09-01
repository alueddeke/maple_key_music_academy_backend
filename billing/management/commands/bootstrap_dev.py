"""
First-boot dev seeding (Aug 28 audit item 16: "seeding is a dependency of
collaboration" — anyone running dev must be able to sign in immediately).

Runs from the dev container entrypoint on every boot, but only ever ACTS on
an empty dev database: if the sentinel demo manager already exists it no-ops,
so restarts never wipe a developer's working data (seed_realistic deletes all
@maplekeytest.com rows — it must not fire on its own mid-work).

Opt out (Nick's --no-data): DEV_SEED=off in the environment.

Refuses to run outside a dev environment: requires DEBUG=True (prod runs
DEBUG=False), independent of what the entrypoint does — defense in depth over
"the prod entrypoint doesn't call it". (DATABASE_URL can't be the signal:
local dev also connects through it.)
"""
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

SENTINEL_EMAIL = 'e2e.manager@maplekeytest.com'
PASSWORD_HINT = 'testpass123'

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed demo data on first dev boot (no-op when already seeded; DEV_SEED=off skips).'

    def handle(self, *args, **options):
        if os.environ.get('DEV_SEED', '').lower() in ('off', '0', 'false'):
            self.stdout.write('bootstrap_dev: DEV_SEED=off — skipping (empty database).')
            return

        if not settings.DEBUG:
            self.stdout.write(self.style.WARNING(
                'bootstrap_dev: refusing — not a dev environment (DEBUG is False).'
            ))
            return

        if User.objects.filter(email=SENTINEL_EMAIL).exists():
            self._print_credentials('already seeded')
            return

        self.stdout.write('bootstrap_dev: empty dev database — seeding demo school...')
        call_command('ensure_e2e_users')
        call_command('seed_realistic')
        self._print_credentials('seeded')

    def _print_credentials(self, state):
        self.stdout.write(self.style.SUCCESS(
            f'\n=== MapleKey dev ({state}) — sign in at http://localhost:5173 ===\n'
            f'  Management: {SENTINEL_EMAIL} / {PASSWORD_HINT}\n'
            f'  Teacher:    teacher.alex.rivera@maplekeytest.com / {PASSWORD_HINT}\n'
            f'  (all @maplekeytest.com users share that password; '
            f'DEV_SEED=off boots with an empty database)\n'
        ))
