# Creates the DatabaseCache table backing settings.CACHES['throttle']
# (shared DRF throttle counters — see custom_auth/throttling.py).
# createcachetable is idempotent: it skips tables that already exist.
from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command('createcachetable', database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0066_historicalprebillinginvoice_excluded_dates_and_more'),
    ]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
