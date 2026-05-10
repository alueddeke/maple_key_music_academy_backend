# Reconciled migration — main branch's real 0041 operations preserved for fresh installs.
# Production already has these changes applied. Dependency updated to use develop's 0040 stub.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0040_batchlessonitem_admin_notes_main'),
    ]

    operations = [
        migrations.AlterField(
            model_name='batchlessonitem',
            name='status',
            field=models.CharField(choices=[('requested', 'Requested'), ('confirmed', 'Confirmed'), ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('trial', 'Trial')], default='completed', max_length=20),
        ),
        migrations.AlterField(
            model_name='historicallesson',
            name='status',
            field=models.CharField(choices=[('requested', 'Requested'), ('confirmed', 'Confirmed'), ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('trial', 'Trial')], default='requested', max_length=20),
        ),
        migrations.AlterField(
            model_name='lesson',
            name='status',
            field=models.CharField(choices=[('requested', 'Requested'), ('confirmed', 'Confirmed'), ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('trial', 'Trial')], default='requested', max_length=20),
        ),
    ]
