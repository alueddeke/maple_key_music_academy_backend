# Generated manually for Phase 3 - Multi-tenancy migration
# Migration 0028: Migrate GlobalRateSettings and SystemSettings to SchoolSettings

from django.db import migrations
from decimal import Decimal


def migrate_settings(apps, schema_editor):
    """
    Copy data from GlobalRateSettings and SystemSettings to SchoolSettings for default school.
    Idempotent: Safe to run multiple times.
    """
    School = apps.get_model('billing', 'School')
    SchoolSettings = apps.get_model('billing', 'SchoolSettings')
    GlobalRateSettings = apps.get_model('billing', 'GlobalRateSettings')
    SystemSettings = apps.get_model('billing', 'SystemSettings')

    # Get default school
    try:
        school = School.objects.get(id=1)
    except School.DoesNotExist:
        raise Exception("Default school (id=1) must exist before migrating settings. Run migration 0027 first.")

    # Check if SchoolSettings already exists
    if SchoolSettings.objects.filter(school=school).exists():
        print("SchoolSettings for default school already exists, skipping creation")
        return

    print("Migrating settings to SchoolSettings...")

    # Get existing settings (use get_or_create for safety)
    global_rates, _ = GlobalRateSettings.objects.get_or_create(
        pk=1,
        defaults={
            'online_teacher_rate': Decimal('45.00'),
            'online_student_rate': Decimal('60.00'),
            'inperson_student_rate': Decimal('100.00'),
        }
    )

    # SystemSettings might not exist in dev databases
    system_settings = SystemSettings.objects.filter(pk=1).first()
    invoice_recipient_email = system_settings.invoice_recipient_email if system_settings else ''

    # Create SchoolSettings for default school
    school_settings = SchoolSettings.objects.create(
        school=school,
        online_teacher_rate=global_rates.online_teacher_rate,
        online_student_rate=global_rates.online_student_rate,
        inperson_student_rate=global_rates.inperson_student_rate,
        invoice_recipient_email=invoice_recipient_email,
        updated_by=global_rates.updated_by,  # Preserve who last updated
    )

    print(f"✓ SchoolSettings created:")
    print(f"  - online_teacher_rate: ${school_settings.online_teacher_rate}")
    print(f"  - online_student_rate: ${school_settings.online_student_rate}")
    print(f"  - inperson_student_rate: ${school_settings.inperson_student_rate}")
    if invoice_recipient_email:
        print(f"  - invoice_recipient_email: {invoice_recipient_email}")

    print("Note: GlobalRateSettings and SystemSettings kept for backward compatibility")


def reverse_migrate_settings(apps, schema_editor):
    """
    Reverse migration: Delete SchoolSettings for default school.
    Safe because GlobalRateSettings and SystemSettings are preserved.
    """
    School = apps.get_model('billing', 'School')
    SchoolSettings = apps.get_model('billing', 'SchoolSettings')

    try:
        school = School.objects.get(id=1)
    except School.DoesNotExist:
        print("Default school doesn't exist, nothing to reverse")
        return

    settings = SchoolSettings.objects.filter(school=school).first()
    if settings:
        print(f"Deleting SchoolSettings for {school.name}")
        settings.delete()
        print("✓ SchoolSettings deleted (GlobalRateSettings preserved)")
    else:
        print("SchoolSettings doesn't exist, nothing to reverse")


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0027_create_default_school'),
    ]

    operations = [
        migrations.RunPython(
            migrate_settings,
            reverse_code=reverse_migrate_settings
        ),
    ]
