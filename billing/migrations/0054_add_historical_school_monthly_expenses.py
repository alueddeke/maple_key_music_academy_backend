"""
0054: Create billing_historicalschoolmonthlyexpenses table.

Migration 0053 was applied to dev DB before CR-03 added HistoricalRecords()
to SchoolMonthlyExpenses, so the shadow table was never created.
"""

import django.db.models.deletion
import simple_history.models
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0053_phase21_dashboard'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='HistoricalSchoolMonthlyExpenses',
            fields=[
                ('id', models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name='ID')),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10)),
                ('notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(blank=True, editable=False)),
                ('updated_at', models.DateTimeField(blank=True, editable=False)),
                ('history_id', models.AutoField(primary_key=True, serialize=False)),
                ('history_date', models.DateTimeField(db_index=True)),
                ('history_change_reason', models.CharField(max_length=100, null=True)),
                ('history_type', models.CharField(choices=[('+', 'Created'), ('~', 'Changed'), ('-', 'Deleted')], max_length=1)),
                ('history_user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('school', models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='billing.school')),
            ],
            options={
                'verbose_name': 'historical school monthly expenses',
                'verbose_name_plural': 'historical school monthly expensess',
                'ordering': ('-history_date', '-history_id'),
                'get_latest_by': ('history_date', 'history_id'),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
    ]
