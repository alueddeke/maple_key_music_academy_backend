"""
0054: No-op.

Originally created the billing_historicalschoolmonthlyexpenses shadow table.
But 0053_phase21_dashboard ALREADY creates that table (its CreateModel for
HistoricalSchoolMonthlyExpenses), so running this CreateModel a second time
fails on any real migrate with:
    ProgrammingError: relation "billing_historicalschoolmonthlyexpenses" already exists
(CI never caught it because the test suite runs with migrations disabled.)

The duplicate is removed here, not from 0053, because production already applied
0053 (which physically created the table). Emptying 0054 lets every environment
converge:
  - fresh install: 0053 creates the table, 0054 is a recorded no-op
  - production:     0053 already created it, 0054 records as applied without re-creating
  - legacy dev:     0054 already applied; this file change is inert
The model stays in migration state via 0053, so makemigrations sees no drift.
"""

from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0053_phase21_dashboard'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = []
