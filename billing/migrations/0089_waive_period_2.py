# MAP-327: two semester windows for the waived-cancellation limit.
#
# Adds the second fixed pair (waive_period_2_start / _end) to SchoolSettings
# and its simple-history shadow table, then fills defaults on existing rows
# (owner ruling 2026-11-03, MAP-303 Q16): semester 1 = Sept 1 – Jan 31,
# semester 2 = Feb 1 – June 30. Only month/day matter while the policy is
# recurring; the years are the first January run. A pair is written only
# where both of its dates are NULL, so a configured semester 1 is kept.
# Reverse drops the columns; the data step is a no-op backwards.

import datetime

from django.db import migrations, models


SEMESTER_1 = (datetime.date(2026, 9, 1), datetime.date(2027, 1, 31))
SEMESTER_2 = (datetime.date(2027, 2, 1), datetime.date(2027, 6, 30))


def set_semester_defaults(apps, schema_editor):
    SchoolSettings = apps.get_model('billing', 'SchoolSettings')
    SchoolSettings.objects.filter(
        waive_period_start__isnull=True, waive_period_end__isnull=True
    ).update(waive_period_start=SEMESTER_1[0], waive_period_end=SEMESTER_1[1])
    SchoolSettings.objects.filter(
        waive_period_2_start__isnull=True, waive_period_2_end__isnull=True
    ).update(waive_period_2_start=SEMESTER_2[0], waive_period_2_end=SEMESTER_2[1])


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0088_ach_returns'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalschoolsettings',
            name='waive_period_2_end',
            field=models.DateField(blank=True, help_text='Second fixed period end (fixed type)', null=True),
        ),
        migrations.AddField(
            model_name='historicalschoolsettings',
            name='waive_period_2_start',
            field=models.DateField(blank=True, help_text='Second fixed period start (fixed type)', null=True),
        ),
        migrations.AddField(
            model_name='schoolsettings',
            name='waive_period_2_end',
            field=models.DateField(blank=True, help_text='Second fixed period end (fixed type)', null=True),
        ),
        migrations.AddField(
            model_name='schoolsettings',
            name='waive_period_2_start',
            field=models.DateField(blank=True, help_text='Second fixed period start (fixed type)', null=True),
        ),
        migrations.RunPython(set_semester_defaults, migrations.RunPython.noop),
    ]
