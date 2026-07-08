"""
Idempotent bootstrap for the Playwright E2E suite.

seed_realistic requires a School and a management user to already exist and
creates neither, so a fresh database (CI) has nothing to log in with. This
command guarantees both, with deterministic credentials the E2E auth setup
(maple-key-music-academy-frontend/e2e/auth.setup.ts) depends on:

    e2e.manager@maplekeytest.com / testpass123

Uses the @maplekeytest.com domain so the existing test teardown covers it.
Safe to run repeatedly and on already-seeded databases.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand

from billing.models import School

E2E_MANAGER_EMAIL = 'e2e.manager@maplekeytest.com'
E2E_PASSWORD = 'testpass123'

User = get_user_model()


class Command(BaseCommand):
    help = 'Ensure the School and deterministic management user the E2E suite logs in with exist.'

    def handle(self, *args, **options):
        school = School.objects.first()
        if school is None:
            school = School.objects.create(
                name='Maple Key E2E School',
                subdomain='e2e-test',
                billing_cycle_day=1,
                email='e2e.school@maplekeytest.com',
                street_address='1 Test Street',
                city='Toronto',
                province='ON',
                postal_code='M1M 1M1',
            )
            self.stdout.write(self.style.SUCCESS(f'Created School: {school.name}'))
        else:
            self.stdout.write(f'Using existing School: {school.name}')

        user, created = User.objects.get_or_create(
            email=E2E_MANAGER_EMAIL,
            defaults={
                'first_name': 'E2E',
                'last_name': 'Manager',
                'user_type': 'management',
                'school': school,
                'is_active': True,
                'is_approved': True,
                'password': make_password(E2E_PASSWORD),
            },
        )
        if not created:
            # Re-assert the fields the E2E suite depends on in case a prior
            # run or manual edit drifted them.
            user.user_type = 'management'
            user.is_active = True
            user.is_approved = True
            user.school = school
            user.password = make_password(E2E_PASSWORD)
            user.save()

        self.stdout.write(self.style.SUCCESS(
            f'{"Created" if created else "Ensured"} management user: {E2E_MANAGER_EMAIL} / {E2E_PASSWORD}'
        ))
