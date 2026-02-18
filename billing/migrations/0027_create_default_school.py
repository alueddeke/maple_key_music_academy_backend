# Generated manually for Phase 3 - Multi-tenancy migration
# Migration 0027: Create default school

from django.db import migrations


def create_default_school(apps, schema_editor):
    """
    Create the default Maple Key Music Academy school.
    Idempotent: Safe to run multiple times.
    """
    School = apps.get_model('billing', 'School')

    # Check if default school already exists
    if School.objects.filter(id=1).exists():
        print("Default school already exists (id=1), skipping creation")
        return

    print("Creating default school: Maple Key Music Academy")

    School.objects.create(
        id=1,
        name='Maple Key Music Academy',
        subdomain='maplekeymusic',

        # Tax rates (Ontario HST)
        hst_rate=13.00,
        gst_rate=5.00,
        pst_rate=0.00,
        tax_number='',  # Can be updated later

        # Billing settings
        billing_cycle_day=1,  # First of month
        payment_terms_days=7,
        cancellation_notice_hours=24,

        # Contact information (Toronto, Ontario)
        email='info@maplekeymusic.com',
        phone_number='',  # Can be updated later
        street_address='123 Music Street',  # Placeholder
        city='Toronto',
        province='ON',
        postal_code='M5H 2N2',  # Downtown Toronto postal code

        # Status
        is_active=True
    )

    print("✓ Default school created successfully")


def reverse_create_default_school(apps, schema_editor):
    """
    Reverse migration: Delete the default school.
    Only safe if no data has been migrated yet.
    """
    School = apps.get_model('billing', 'School')
    User = apps.get_model('billing', 'User')
    Lesson = apps.get_model('billing', 'Lesson')
    Invoice = apps.get_model('billing', 'Invoice')
    BillableContact = apps.get_model('billing', 'BillableContact')

    # Safety check: Don't delete if any data is linked to this school
    school = School.objects.filter(id=1).first()
    if not school:
        print("Default school doesn't exist, nothing to reverse")
        return

    # Check for linked data
    users_count = User.objects.filter(school_id=1).count()
    lessons_count = Lesson.objects.filter(school_id=1).count()
    invoices_count = Invoice.objects.filter(school_id=1).count()
    contacts_count = BillableContact.objects.filter(school_id=1).count()

    if any([users_count, lessons_count, invoices_count, contacts_count]):
        raise Exception(
            f"Cannot reverse: School has linked data "
            f"({users_count} users, {lessons_count} lessons, "
            f"{invoices_count} invoices, {contacts_count} contacts). "
            f"Data must be migrated away first."
        )

    print("Deleting default school (no linked data found)")
    school.delete()
    print("✓ Default school deleted")


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0026_add_school_fk_to_invoice_and_recipients'),
    ]

    operations = [
        migrations.RunPython(
            create_default_school,
            reverse_code=reverse_create_default_school
        ),
    ]
