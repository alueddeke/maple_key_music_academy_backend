#!/usr/bin/env python
"""
Diagnostic script to check InvoiceRecipientEmail model status
Run this on the production server to diagnose the 500 error
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maple_key_backend.settings')
django.setup()

print("=" * 70)
print("PRODUCTION DIAGNOSTIC - InvoiceRecipientEmail")
print("=" * 70)

# Test 1: Check if model is imported
print("\n1. Testing model import...")
try:
    from billing.models import InvoiceRecipientEmail
    print("   ✓ InvoiceRecipientEmail model imported successfully")
except ImportError as e:
    print(f"   ✗ FAILED to import InvoiceRecipientEmail: {e}")
    exit(1)

# Test 2: Check if table exists in database
print("\n2. Checking database table...")
try:
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'billing_invoicerecipientemail'
            );
        """)
        exists = cursor.fetchone()[0]
        if exists:
            print("   ✓ Table 'billing_invoicerecipientemail' exists in database")
        else:
            print("   ✗ Table 'billing_invoicerecipientemail' DOES NOT EXIST")
            print("   → Migrations may not have run")
            exit(1)
except Exception as e:
    print(f"   ✗ Error checking table: {e}")
    exit(1)

# Test 3: Check if we can query the model
print("\n3. Testing model query...")
try:
    count = InvoiceRecipientEmail.objects.count()
    print(f"   ✓ Query successful - {count} recipient(s) in database")
except Exception as e:
    print(f"   ✗ Query failed: {e}")
    exit(1)

# Test 4: Check serializer
print("\n4. Testing serializer...")
try:
    from billing.serializers import InvoiceRecipientEmailSerializer
    print("   ✓ InvoiceRecipientEmailSerializer imported successfully")

    recipients = InvoiceRecipientEmail.objects.all()
    serializer = InvoiceRecipientEmailSerializer(recipients, many=True)
    data = serializer.data
    print(f"   ✓ Serialization successful - {len(data)} recipient(s)")
    for item in data:
        print(f"     - {item['email']}")
except Exception as e:
    print(f"   ✗ Serializer test failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Test 5: Check migrations status
print("\n5. Checking migration status...")
try:
    from django.db.migrations.recorder import MigrationRecorder
    recorder = MigrationRecorder(connection)

    # Check for our specific migrations
    migrations_to_check = [
        '0013_alter_lesson_lesson_type_systemsettings',
        '0014_invoicerecipientemail',
        '0015_migrate_existing_email_to_recipients'
    ]

    applied = recorder.applied_migrations()
    for migration_name in migrations_to_check:
        is_applied = any(m[1] == migration_name and m[0] == 'billing' for m in applied)
        status = "✓ Applied" if is_applied else "✗ NOT APPLIED"
        print(f"   {status}: billing.{migration_name}")

except Exception as e:
    print(f"   ✗ Error checking migrations: {e}")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
