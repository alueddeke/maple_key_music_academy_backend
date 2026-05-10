from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0043_remove_lesson_rate'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='parent_email',
        ),
        migrations.RemoveField(
            model_name='user',
            name='parent_phone',
        ),
    ]
