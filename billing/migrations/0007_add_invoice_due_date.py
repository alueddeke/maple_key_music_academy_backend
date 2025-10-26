# Generated manually to add due_date field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0006_increase_duration_field_size'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='due_date',
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
