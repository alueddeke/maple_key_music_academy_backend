"""
Management command to migrate ALLOWED_EMAILS environment variable to database-driven approval system.

This command:
1. Reads emails from ALLOWED_EMAILS setting
2. For each email:
   - If User exists: Set is_approved=True
   - If User doesn't exist: Create ApprovedEmail entry
3. Displays migration results

Usage:
    python manage.py migrate_allowed_emails
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.auth import get_user_model
from billing.models import ApprovedEmail

User = get_user_model()


class Command(BaseCommand):
    help = 'Migrate ALLOWED_EMAILS from environment variable to database approval system'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Starting ALLOWED_EMAILS migration...'))
        self.stdout.write('')

        # Get ALLOWED_EMAILS from settings
        allowed_emails = getattr(settings, 'ALLOWED_EMAILS', [])

        if not allowed_emails:
            self.stdout.write(self.style.WARNING('No emails found in ALLOWED_EMAILS setting.'))
            self.stdout.write('ALLOWED_EMAILS is either empty or not configured.')
            return

        self.stdout.write(f'Found {len(allowed_emails)} email(s) in ALLOWED_EMAILS:')
        for email in allowed_emails:
            self.stdout.write(f'  - {email}')
        self.stdout.write('')

        # Track results
        approved_users = []
        created_approved_emails = []
        skipped = []

        # Process each email
        for email in allowed_emails:
            email = email.strip().lower()

            # Check if User exists
            try:
                user = User.objects.get(email=email)

                if user.is_approved:
                    skipped.append((email, f'{user.get_user_type_display()} - already approved'))
                else:
                    user.is_approved = True
                    user.save()
                    approved_users.append((email, user.get_user_type_display()))

            except User.DoesNotExist:
                # User doesn't exist - create ApprovedEmail entry
                try:
                    approved_email, created = ApprovedEmail.objects.get_or_create(
                        email=email,
                        defaults={
                            'user_type': 'teacher',  # Default to teacher
                            'notes': 'Migrated from ALLOWED_EMAILS environment variable',
                            'approved_by_id': User.objects.filter(user_type='management', is_superuser=True).first().id
                        }
                    )

                    if created:
                        created_approved_emails.append((email, 'teacher'))
                    else:
                        skipped.append((email, 'ApprovedEmail already exists'))

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Failed to create ApprovedEmail for {email}: {str(e)}'))

        # Display results
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('MIGRATION COMPLETE'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')

        if approved_users:
            self.stdout.write(self.style.SUCCESS(f'✓ Approved {len(approved_users)} existing user(s):'))
            for email, user_type in approved_users:
                self.stdout.write(f'  - {email} ({user_type})')
            self.stdout.write('')

        if created_approved_emails:
            self.stdout.write(self.style.SUCCESS(f'✓ Created {len(created_approved_emails)} pre-approved email(s):'))
            for email, user_type in created_approved_emails:
                self.stdout.write(f'  - {email} (default: {user_type})')
            self.stdout.write('')

        if skipped:
            self.stdout.write(self.style.WARNING(f'⊘ Skipped {len(skipped)} email(s):'))
            for email, reason in skipped:
                self.stdout.write(f'  - {email} ({reason})')
            self.stdout.write('')

        self.stdout.write(self.style.MIGRATE_HEADING('Next Steps:'))
        self.stdout.write('1. Verify the migration results above')
        self.stdout.write('2. Remove ALLOWED_EMAILS from settings.py')
        self.stdout.write('3. Remove ALLOWED_EMAILS from .env files')
        self.stdout.write('4. Remove ALLOWED_EMAILS from GitHub Secrets (production)')
        self.stdout.write('5. Update documentation')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Migration completed successfully!'))
