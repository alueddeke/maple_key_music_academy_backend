# Generated manually on 2026-01-30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0020_remove_user_assigned_teacher_user_assigned_teachers_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='billablecontact',
            old_name='state',
            new_name='province',
        ),
        migrations.AlterField(
            model_name='billablecontact',
            name='province',
            field=models.CharField(help_text='Province code (e.g., ON, BC, QC)', max_length=2),
        ),
        migrations.AlterField(
            model_name='billablecontact',
            name='postal_code',
            field=models.CharField(help_text='Postal code (e.g., M5H 2N2)', max_length=10),
        ),
    ]
