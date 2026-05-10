from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0042_drop_allauth_tables'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='lesson',
            name='rate',
        ),
    ]
