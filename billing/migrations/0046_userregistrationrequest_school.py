import django.db.models.deletion
from django.db import migrations, models


def assign_school_to_existing_requests(apps, schema_editor):
    UserRegistrationRequest = apps.get_model('billing', 'UserRegistrationRequest')
    School = apps.get_model('billing', 'School')
    try:
        school = School.objects.get()
        UserRegistrationRequest.objects.filter(school__isnull=True).update(school=school)
    except (School.DoesNotExist, School.MultipleObjectsReturned):
        pass  # No school or multiple schools — leave nulls for manual resolution


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0045_remove_historicallesson_rate_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userregistrationrequest",
            name="school",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="registration_requests",
                to="billing.school",
            ),
        ),
        migrations.AddField(
            model_name="historicaluserregistrationrequest",
            name="school",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="billing.school",
            ),
        ),
        migrations.RunPython(
            assign_school_to_existing_requests,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
