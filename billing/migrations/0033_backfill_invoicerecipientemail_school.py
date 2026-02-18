# Generated manually for Phase 3 - Multi-tenancy migration
# Migration 0033: Backfill InvoiceRecipientEmail.school with default school

from django.db import migrations


def backfill_invoicerecipientemail_school(apps, schema_editor):
    """
    Assign all invoice recipient emails to the default school (id=1).
    Idempotent: Safe to run multiple times.
    """
    School = apps.get_model('billing', 'School')
    InvoiceRecipientEmail = apps.get_model('billing', 'InvoiceRecipientEmail')

    # Get default school
    try:
        school = School.objects.get(id=1)
    except School.DoesNotExist:
        raise Exception("Default school (id=1) must exist before backfilling. Run migration 0027 first.")

    # Count recipients without school
    recipients_without_school = InvoiceRecipientEmail.objects.filter(school__isnull=True)
    count = recipients_without_school.count()

    if count == 0:
        print("All invoice recipients already have school assigned, skipping backfill")
        return

    print(f"Backfilling {count} invoice recipients with school: {school.name}")

    # Bulk update for efficiency
    recipients_without_school.update(school=school)

    print(f"✓ {count} invoice recipients assigned to {school.name}")

    # Verification
    orphaned = InvoiceRecipientEmail.objects.filter(school__isnull=True).count()
    if orphaned > 0:
        raise Exception(f"ERROR: {orphaned} invoice recipients still have no school after backfill!")

    print("✓ Verification passed: All invoice recipients have school assigned")


def reverse_backfill_invoicerecipientemail_school(apps, schema_editor):
    """
    Reverse migration: Clear school FK for all invoice recipients assigned to default school.
    """
    InvoiceRecipientEmail = apps.get_model('billing', 'InvoiceRecipientEmail')

    recipients_with_school = InvoiceRecipientEmail.objects.filter(school_id=1)
    count = recipients_with_school.count()

    if count == 0:
        print("No invoice recipients assigned to default school, nothing to reverse")
        return

    print(f"Clearing school assignment for {count} invoice recipients")
    recipients_with_school.update(school=None)
    print(f"✓ {count} invoice recipients cleared")


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0032_backfill_billablecontact_school'),
    ]

    operations = [
        migrations.RunPython(
            backfill_invoicerecipientemail_school,
            reverse_code=reverse_backfill_invoicerecipientemail_school
        ),
    ]
