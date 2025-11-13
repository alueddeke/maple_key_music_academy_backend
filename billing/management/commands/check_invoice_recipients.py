"""
Management command to diagnose InvoiceRecipientEmail issues in production
Usage: python manage.py check_invoice_recipients
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Diagnose InvoiceRecipientEmail model and database status'

    def handle(self, *args, **options):
        self.stdout.write("=" * 70)
        self.stdout.write("DIAGNOSTIC: InvoiceRecipientEmail")
        self.stdout.write("=" * 70)

        # Test 1: Import model
        self.stdout.write("\n1. Testing model import...")
        try:
            from billing.models import InvoiceRecipientEmail
            self.stdout.write(self.style.SUCCESS("   ✓ Model imported"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ✗ Import failed: {e}"))
            return

        # Test 2: Check table exists
        self.stdout.write("\n2. Checking database table...")
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name LIKE 'billing_%'
                    ORDER BY table_name;
                """)
                tables = cursor.fetchall()

                table_list = [t[0] for t in tables]
                if 'billing_invoicerecipientemail' in table_list:
                    self.stdout.write(self.style.SUCCESS("   ✓ Table exists"))
                else:
                    self.stdout.write(self.style.ERROR("   ✗ Table MISSING"))
                    self.stdout.write("   Available billing tables:")
                    for table in table_list:
                        self.stdout.write(f"     - {table}")
                    return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ✗ Error: {e}"))
            return

        # Test 3: Query model
        self.stdout.write("\n3. Testing model query...")
        try:
            count = InvoiceRecipientEmail.objects.count()
            self.stdout.write(self.style.SUCCESS(f"   ✓ {count} recipient(s) found"))

            if count > 0:
                self.stdout.write("   Existing recipients:")
                for recipient in InvoiceRecipientEmail.objects.all():
                    self.stdout.write(f"     - {recipient.email}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ✗ Query failed: {e}"))
            import traceback
            self.stdout.write(traceback.format_exc())
            return

        # Test 4: Check migrations
        self.stdout.write("\n4. Checking migrations...")
        try:
            from django.db.migrations.recorder import MigrationRecorder
            recorder = MigrationRecorder(connection)

            migrations = [
                '0013_alter_lesson_lesson_type_systemsettings',
                '0014_invoicerecipientemail',
                '0015_migrate_existing_email_to_recipients'
            ]

            applied = recorder.applied_migrations()
            for mig in migrations:
                is_applied = any(m[1] == mig and m[0] == 'billing' for m in applied)
                if is_applied:
                    self.stdout.write(self.style.SUCCESS(f"   ✓ {mig}"))
                else:
                    self.stdout.write(self.style.ERROR(f"   ✗ {mig} NOT APPLIED"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ✗ Error: {e}"))

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("DIAGNOSTIC COMPLETE"))
        self.stdout.write("=" * 70)
