# Generated manually 2026-05-06
# Drops allauth tables before allauth is removed from INSTALLED_APPS.
# CRITICAL: This migration must be applied (python manage.py migrate)
# BEFORE allauth is removed from INSTALLED_APPS in settings.py.
# If allauth is removed first, Django migration history may be inconsistent.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0041_add_trial_lesson_status'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DROP TABLE IF EXISTS socialaccount_socialtoken CASCADE;
                DROP TABLE IF EXISTS socialaccount_socialaccount CASCADE;
                DROP TABLE IF EXISTS socialaccount_socialapp_sites CASCADE;
                DROP TABLE IF EXISTS socialaccount_socialapp CASCADE;
                DROP TABLE IF EXISTS account_emailconfirmation CASCADE;
                DROP TABLE IF EXISTS account_emailaddress CASCADE;
                DROP TABLE IF EXISTS django_site CASCADE;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
