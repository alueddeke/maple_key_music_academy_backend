"""MAP-229: copy the legacy User.instruments string into TeacherInstrument rows.

Every token must match (case-insensitively) an instrument on the user's
school list, and only teachers may carry a string (D2, owner 2026-09-28).
Any violation raises before the first write and names every offender, so the
deploy's migration step fails instead of dropping data. Copied rows carry no
skill level (D1). billing 0083 drops the column after this runs.

backfill() and names_by_teacher() take model classes so the tests can drive
them against the live registry (pytest runs with --no-migrations and the live
User model no longer has the column).
"""
from django.db import migrations


def backfill(entries, SchoolInstrument, TeacherProfile, TeacherInstrument):
    """entries: iterable of (user_id, user_type, school_id, raw string)."""
    problems = []
    plan = []
    for user_id, user_type, school_id, raw in entries:
        tokens = [t.strip() for t in raw.split(',') if t.strip()]
        if not tokens:
            continue
        if user_type != 'teacher':
            problems.append((user_id, f'{user_type} has instruments {raw!r}'))
            continue
        vocab = {
            name.lower(): name
            for name in SchoolInstrument.objects.filter(school_id=school_id)
            .values_list('name', flat=True)
        }
        names = []
        for token in tokens:
            canonical = vocab.get(token.lower())
            if canonical is None:
                problems.append((user_id, token))
            elif canonical not in names:
                names.append(canonical)
        plan.append((user_id, school_id, names))

    if problems:
        raise RuntimeError(
            'MAP-229 backfill refused; fix these User.instruments values first: '
            + '; '.join(f'user {uid}: {what}' for uid, what in problems)
        )

    for user_id, school_id, names in plan:
        profile, _ = TeacherProfile.objects.get_or_create(
            teacher_id=user_id, defaults={'school_id': school_id}
        )
        have = {
            n.lower() for n in profile.instruments.values_list('instrument', flat=True)
        }
        for name in names:
            if name.lower() not in have:
                TeacherInstrument.objects.create(
                    profile=profile, instrument=name, skill_ceiling=None
                )


def names_by_teacher(TeacherProfile):
    """{teacher_id: 'A, B'} from the rows, in instrument-name order."""
    result = {}
    for profile in TeacherProfile.objects.all():
        names = profile.instruments.order_by('instrument').values_list('instrument', flat=True)
        joined = ', '.join(names)
        if joined:
            result[profile.teacher_id] = joined
    return result


def forward(apps, schema_editor):
    User = apps.get_model('billing', 'User')
    entries = User.objects.exclude(instruments='').values_list(
        'id', 'user_type', 'school_id', 'instruments'
    )
    backfill(
        entries,
        apps.get_model('teacher_profiles', 'SchoolInstrument'),
        apps.get_model('teacher_profiles', 'TeacherProfile'),
        apps.get_model('teacher_profiles', 'TeacherInstrument'),
    )


def reverse(apps, schema_editor):
    User = apps.get_model('billing', 'User')
    for teacher_id, joined in names_by_teacher(
        apps.get_model('teacher_profiles', 'TeacherProfile')
    ).items():
        User.objects.filter(pk=teacher_id).update(instruments=joined)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0082_user_online_hourly_rate'),
        ('teacher_profiles', '0004_teacherinstrument_skill_ceiling_nullable'),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
