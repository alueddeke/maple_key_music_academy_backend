# Generated manually for Phase 3 - Multi-tenancy migration
# Migration 0029: Backfill User.school with default school

from django.db import migrations


def backfill_user_school(apps, schema_editor):
    """
    Assign all users to the default school (id=1).
    Idempotent: Safe to run multiple times.
    """
    School = apps.get_model('billing', 'School')
    User = apps.get_model('billing', 'User')

    # Get default school
    try:
        school = School.objects.get(id=1)
    except School.DoesNotExist:
        raise Exception("Default school (id=1) must exist before backfilling. Run migration 0027 first.")

    # Count users without school
    users_without_school = User.objects.filter(school__isnull=True)
    count = users_without_school.count()

    if count == 0:
        print("All users already have school assigned, skipping backfill")
        return

    print(f"Backfilling {count} users with school: {school.name}")

    # Bulk update for efficiency
    users_without_school.update(school=school)

    print(f"✓ {count} users assigned to {school.name}")

    # Verification
    orphaned = User.objects.filter(school__isnull=True).count()
    if orphaned > 0:
        raise Exception(f"ERROR: {orphaned} users still have no school after backfill!")

    print("✓ Verification passed: All users have school assigned")


def reverse_backfill_user_school(apps, schema_editor):
    """
    Reverse migration: Clear school FK for all users assigned to default school.
    """
    User = apps.get_model('billing', 'User')

    users_with_school = User.objects.filter(school_id=1)
    count = users_with_school.count()

    if count == 0:
        print("No users assigned to default school, nothing to reverse")
        return

    print(f"Clearing school assignment for {count} users")
    users_with_school.update(school=None)
    print(f"✓ {count} users cleared")


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0028_migrate_settings_to_schoolsettings'),
    ]

    operations = [
        migrations.RunPython(
            backfill_user_school,
            reverse_code=reverse_backfill_user_school
        ),
    ]
