# Generated manually on 2026-02-01
# Removes obsolete address fields from billing_user table that were left over
# from migration 0020 which migrated students from separate Student model to User model

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0022_rename_state_to_province'),
    ]

    operations = [
        migrations.RunSQL(
            # Forward: Drop obsolete columns that exist in DB but not in Django models
            sql="""
                ALTER TABLE billing_user
                DROP COLUMN IF EXISTS city,
                DROP COLUMN IF EXISTS postal_code,
                DROP COLUMN IF EXISTS province_state,
                DROP COLUMN IF EXISTS country;
            """,
            # Reverse: Cannot be reversed (columns would need to be recreated)
            reverse_sql=migrations.RunSQL.noop
        ),
    ]
