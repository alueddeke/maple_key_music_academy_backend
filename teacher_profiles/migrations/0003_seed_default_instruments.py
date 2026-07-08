"""Seed a starter instrument list for every existing school.

Management curates this list from the UI afterwards — this only prevents
the dropdowns from starting empty on deploy.
"""
from django.db import migrations

DEFAULT_INSTRUMENTS = [
    'Piano',
    'Guitar',
    'Bass',
    'Drums',
    'Voice',
    'Violin',
    'Ukulele',
    'Flute',
    'Saxophone',
]


def seed_instruments(apps, schema_editor):
    School = apps.get_model('billing', 'School')
    SchoolInstrument = apps.get_model('teacher_profiles', 'SchoolInstrument')
    for school in School.objects.all():
        for name in DEFAULT_INSTRUMENTS:
            SchoolInstrument.objects.get_or_create(school=school, name=name)


def unseed_instruments(apps, schema_editor):
    SchoolInstrument = apps.get_model('teacher_profiles', 'SchoolInstrument')
    SchoolInstrument.objects.filter(name__in=DEFAULT_INSTRUMENTS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
        ('teacher_profiles', '0002_historicalschoolinstrument_schoolinstrument'),
    ]

    operations = [
        migrations.RunPython(seed_instruments, unseed_instruments),
    ]
