# Generated manually for Phase 3 - Multi-tenancy migration
# Migration 0032: Backfill BillableContact.school from student's school

from django.db import migrations


def backfill_billablecontact_school(apps, schema_editor):
    """
    Assign each billable contact to the student's school.
    Idempotent: Safe to run multiple times.
    """
    BillableContact = apps.get_model('billing', 'BillableContact')
    School = apps.get_model('billing', 'School')

    # Verify default school exists
    try:
        default_school = School.objects.get(id=1)
    except School.DoesNotExist:
        raise Exception("Default school (id=1) must exist. Run migration 0027 first.")

    # Get contacts without school
    contacts_without_school = BillableContact.objects.filter(school__isnull=True).select_related('student')
    count = contacts_without_school.count()

    if count == 0:
        print("All billable contacts already have school assigned, skipping backfill")
        return

    print(f"Backfilling {count} billable contacts with student's school")

    # Process each contact
    updated = 0
    default_assigned = 0

    for contact in contacts_without_school:
        if contact.student and contact.student.school_id:
            # Assign to student's school
            contact.school_id = contact.student.school_id
            updated += 1
        else:
            # Student has no school, use default
            contact.school_id = default_school.id
            default_assigned += 1
            updated += 1

    # Bulk update for efficiency
    BillableContact.objects.bulk_update(contacts_without_school, ['school'])

    print(f"✓ {updated} billable contacts assigned to school")
    if default_assigned > 0:
        print(f"  - {default_assigned} contacts assigned to default school (student had no school)")

    # Verification
    orphaned = BillableContact.objects.filter(school__isnull=True).count()
    if orphaned > 0:
        raise Exception(f"ERROR: {orphaned} billable contacts still have no school after backfill!")

    print("✓ Verification passed: All billable contacts have school assigned")


def reverse_backfill_billablecontact_school(apps, schema_editor):
    """
    Reverse migration: Clear school FK for all billable contacts.
    """
    BillableContact = apps.get_model('billing', 'BillableContact')

    contacts_with_school = BillableContact.objects.filter(school__isnull=False)
    count = contacts_with_school.count()

    if count == 0:
        print("No billable contacts have school assigned, nothing to reverse")
        return

    print(f"Clearing school assignment for {count} billable contacts")
    contacts_with_school.update(school=None)
    print(f"✓ {count} billable contacts cleared")


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0031_backfill_invoice_school'),
    ]

    operations = [
        migrations.RunPython(
            backfill_billablecontact_school,
            reverse_code=reverse_backfill_billablecontact_school
        ),
    ]
