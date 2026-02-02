# Generated manually on 2026-01-30

from django.db import migrations, models


def rename_state_to_province(apps, schema_editor):
    """Rename state to province if state column exists"""
    with schema_editor.connection.cursor() as cursor:
        # Check if state column exists (it won't in fresh local databases)
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns
                WHERE table_name = 'billing_billablecontact' AND column_name = 'state'
            );
        """)
        state_exists = cursor.fetchone()[0]

        if state_exists:
            print("Renaming state column to province...")
            cursor.execute("""
                ALTER TABLE billing_billablecontact RENAME COLUMN state TO province;
            """)
        else:
            print("State column doesn't exist - skipping rename (local dev database)")


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0021_remove_user_assigned_teacher_user_assigned_teachers_and_more'),
    ]

    operations = [
        migrations.RunPython(rename_state_to_province, migrations.RunPython.noop),
        # Use SeparateDatabaseAndState since the field might already be 'province' in fresh databases
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='billablecontact',
                    name='province',
                    field=models.CharField(help_text='Province code (e.g., ON, BC, QC)', max_length=2),
                ),
                migrations.AlterField(
                    model_name='billablecontact',
                    name='postal_code',
                    field=models.CharField(help_text='Postal code (e.g., M5H 2N2)', max_length=10),
                ),
            ],
            database_operations=[],  # No database changes needed - models.py already has correct field definitions
        ),
    ]
