"""
MAP-229: migration teacher_profiles 0005_backfill_user_instruments.

pytest runs with --no-migrations and the live User model no longer has the
`instruments` column, so the migration's backfill()/names_by_teacher() are
driven directly with (user_id, user_type, school_id, raw) entries and the live
models. forward()/reverse() are one query each around them; the full chain
(refuse → forward → reverse → forward) was drilled on the local dev DB and is
recorded on the ticket. Assertions are on rows, never on SQL.
"""
import importlib

import pytest

from teacher_profiles.models import SchoolInstrument, TeacherInstrument, TeacherProfile

migration = importlib.import_module('teacher_profiles.migrations.0005_backfill_user_instruments')


def _run(entries):
    migration.backfill(entries, SchoolInstrument, TeacherProfile, TeacherInstrument)


def _rows(user):
    return list(
        TeacherInstrument.objects.filter(profile__teacher=user)
        .order_by('instrument')
        .values_list('instrument', 'skill_ceiling')
    )


@pytest.fixture
def vocab(school):
    for name in ('Banjo', 'Guitar', 'Piano', 'Voice'):
        SchoolInstrument.objects.get_or_create(school=school, name=name)


@pytest.mark.django_db
class TestInstrumentBackfill:

    def test_creates_canonical_rows_without_skill(self, teacher_user, vocab):
        _run([(teacher_user.id, 'teacher', teacher_user.school_id, 'Piano, banjo , Guitar, piano,')])

        assert _rows(teacher_user) == [('Banjo', None), ('Guitar', None), ('Piano', None)]

    def test_keeps_existing_row_and_its_skill(self, teacher_user, vocab):
        profile = TeacherProfile.objects.create(teacher=teacher_user, school=teacher_user.school)
        TeacherInstrument.objects.create(profile=profile, instrument='Guitar', skill_ceiling='advanced')

        _run([(teacher_user.id, 'teacher', teacher_user.school_id, 'guitar, Voice')])

        assert _rows(teacher_user) == [('Guitar', 'advanced'), ('Voice', None)]
        assert TeacherProfile.objects.filter(teacher=teacher_user).count() == 1

    def test_creates_profile_on_the_users_school(self, teacher_user, vocab):
        assert not TeacherProfile.objects.filter(teacher=teacher_user).exists()

        _run([(teacher_user.id, 'teacher', teacher_user.school_id, 'Piano')])

        profile = TeacherProfile.objects.get(teacher=teacher_user)
        assert profile.school_id == teacher_user.school_id
        assert _rows(teacher_user) == [('Piano', None)]

    def test_unmatched_token_refuses_and_writes_nothing(self, teacher_user, second_school, vocab):
        from django.contrib.auth import get_user_model
        other = get_user_model().objects.create_user(
            email='other-teacher@test.com', password='x', user_type='teacher',
            first_name='O', last_name='T', school=teacher_user.school, is_approved=True,
        )

        with pytest.raises(RuntimeError) as exc:
            _run([
                (teacher_user.id, 'teacher', teacher_user.school_id, 'Piano'),
                (other.id, 'teacher', other.school_id, 'Guitar, Kazoo'),
            ])

        assert f'user {other.id}: Kazoo' in str(exc.value)
        assert not TeacherProfile.objects.filter(teacher__in=[teacher_user, other]).exists()
        assert not TeacherInstrument.objects.exists()

    def test_token_matched_against_own_school_only(self, teacher_user, second_school, vocab):
        """A name on another school's list is still unmatched for this user."""
        SchoolInstrument.objects.create(school=second_school, name='Cello')

        with pytest.raises(RuntimeError) as exc:
            _run([(teacher_user.id, 'teacher', teacher_user.school_id, 'Cello')])

        assert f'user {teacher_user.id}: Cello' in str(exc.value)
        assert not TeacherInstrument.objects.exists()

    def test_non_teacher_with_string_refuses(self, student_user, vocab):
        with pytest.raises(RuntimeError) as exc:
            _run([(student_user.id, 'student', student_user.school_id, 'Piano')])

        assert f'user {student_user.id}: student has instruments' in str(exc.value)
        assert not TeacherProfile.objects.filter(teacher=student_user).exists()

    def test_names_by_teacher_rebuilds_string_for_reverse(self, teacher_user, vocab):
        _run([(teacher_user.id, 'teacher', teacher_user.school_id, 'Voice, Piano')])

        assert migration.names_by_teacher(TeacherProfile) == {teacher_user.id: 'Piano, Voice'}
