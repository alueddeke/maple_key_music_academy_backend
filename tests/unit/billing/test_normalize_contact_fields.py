"""MAP-293 Section D: `normalize_contact_fields` cleans stored phones and
postal codes on User, BillableContact and School (owner runs it in prod).

--dry-run prints counts and writes nothing; --apply writes and is idempotent;
a value that cannot be normalised is reported by id and left as stored.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from billing.models import BillableContact, School, User


def _run(*flags):
    out = StringIO()
    call_command('normalize_contact_fields', *flags, stdout=out)
    return out.getvalue()


@pytest.fixture
def messy(school, student_user, teacher_user):
    """One normalisable value per model/field, plus one that cannot be."""
    User.objects.filter(pk=student_user.pk).update(phone_number='(416) 822-8104')
    User.objects.filter(pk=teacher_user.pk).update(phone_number='822-8104', postal_code='k1a0b1')
    School.objects.filter(pk=school.pk).update(phone_number='+1 416 555 0100', postal_code='m5h2n2')
    contact = BillableContact.objects.create(
        student=student_user, school=school, contact_type='parent',
        first_name='Pat', last_name='Parent', email='pat@parent.com', phone='416.555.0101',
        street_address='1 Main St', city='Toronto', province='ON', postal_code='M5H 2N2',
        is_primary=True,
    )
    return {'student': student_user, 'teacher': teacher_user, 'school': school, 'contact': contact}


def _stored(messy):
    for obj in messy.values():
        obj.refresh_from_db()
    return (
        messy['student'].phone_number,
        messy['teacher'].phone_number, messy['teacher'].postal_code,
        messy['school'].phone_number, messy['school'].postal_code,
        messy['contact'].phone, messy['contact'].postal_code,
    )


@pytest.mark.django_db
def test_dry_run_reports_counts_and_writes_nothing(messy):
    before = _stored(messy)
    history_before = User.history.count() + BillableContact.history.count()

    out = _run('--dry-run')

    assert _stored(messy) == before
    assert User.history.count() + BillableContact.history.count() == history_before
    assert 'DRY RUN' in out
    assert 'User.phone_number: 1 to change' in out
    assert 'User.postal_code: 1 to change' in out
    assert 'BillableContact.phone: 1 to change' in out
    assert 'School.phone_number: 1 to change' in out
    assert 'School.postal_code: 1 to change' in out
    assert f"skipped User id={messy['teacher'].pk} phone_number" in out
    # Stored values are personal data: the report names rows, never values.
    assert '822-8104' not in out


@pytest.mark.django_db
def test_apply_stores_canonical_values_and_skips_unparseable(messy):
    out = _run('--apply')

    assert _stored(messy) == (
        '4168228104',
        '822-8104', 'K1A 0B1',
        '4165550100', 'M5H 2N2',
        '4165550101', 'M5H 2N2',
    )
    assert 'APPLIED' in out
    assert f"skipped User id={messy['teacher'].pk} phone_number" in out
    assert messy['contact'].history.first().phone == '4165550101'


@pytest.mark.django_db
def test_second_apply_changes_nothing(messy):
    _run('--apply')
    after_first = _stored(messy)

    out = _run('--apply')

    assert _stored(messy) == after_first
    # Six model/field pairs, none with anything left to change.
    assert out.count(': 0 to change') == 6


@pytest.mark.django_db
def test_blank_values_are_left_blank(student_user):
    User.objects.filter(pk=student_user.pk).update(phone_number='', postal_code='')

    _run('--apply')

    student_user.refresh_from_db()
    assert (student_user.phone_number, student_user.postal_code) == ('', '')


@pytest.mark.django_db
@pytest.mark.parametrize('flags', [(), ('--dry-run', '--apply')])
def test_exactly_one_mode_is_required(flags):
    with pytest.raises(CommandError):
        _run(*flags)
