"""DRILL (MAP-165 D2) — do not merge. Reproduces the 2026-07-08 class: a migration
that assumes a table no migration creates (legacy prod-only table).
Must fail migrate-from-empty."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0084_schoolsettings_invoice_reply_to_email'),
    ]

    operations = [
        migrations.RunSQL(
            "UPDATE billing_legacy_drill_contact SET province = 'ON' WHERE province IS NULL",
            migrations.RunSQL.noop,
        ),
    ]
