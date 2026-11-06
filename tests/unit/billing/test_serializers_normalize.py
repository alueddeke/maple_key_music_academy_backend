"""MAP-293 Section D: contact fields are normalized by the input serializers.

The rules (the frontend's src/schemas/normalize.ts mirrors them):
- phone: digits only, a leading 1 on 11 digits dropped, else "Enter a
  10-digit phone number"; blank only where the field is optional
- names: trimmed, inner spaces collapsed, Title Case after a space, `-` or
  `'` unless an uppercase letter already follows position 0
- city: a trailing ", <province code or name>" is dropped when it matches
  the province that is set
- postal code: A1A 1A1
- email: trimmed, lowercase
"""

import pytest

from billing.serializers import (
    BillableContactSerializer,
    BillingContactInputSerializer,
    SchoolSerializer,
    StudentCreateSerializer,
    TeacherUpdateSerializer,
)

PHONE_ERROR = 'Enter a 10-digit phone number'


def _contact(**overrides):
    return {
        'contact_type': 'parent', 'first_name': 'Pat', 'last_name': 'Parent',
        'email': 'pat@parent.com', 'phone': '4165550100',
        'street_address': '1 Main St', 'city': 'Toronto', 'province': 'ON',
        'postal_code': 'M5H 2N2',
    } | overrides


def _valid(serializer):
    assert serializer.is_valid(), serializer.errors
    return serializer.validated_data


@pytest.mark.parametrize('raw', [
    '416 822 8104', '(416) 822-8104', '+1 416-822-8104', '4168228104',
    '1-416-822-8104', '+1 (416) 822-8104', '416.822.8104',
])
def test_phone_inputs_store_ten_digits(raw):
    assert _valid(BillingContactInputSerializer(data=_contact(phone=raw)))['phone'] == '4168228104'


@pytest.mark.parametrize('raw', ['822 8104', '416 822 81045', '2-416-822-8104', 'no phone'])
def test_phone_that_is_not_ten_digits_is_rejected(raw):
    serializer = BillingContactInputSerializer(data=_contact(phone=raw))

    assert not serializer.is_valid()
    assert serializer.errors['phone'] == [PHONE_ERROR]


def test_required_contact_phone_cannot_be_blank():
    serializer = BillingContactInputSerializer(data=_contact(phone=''))

    assert not serializer.is_valid()
    assert 'phone' in serializer.errors


@pytest.mark.parametrize('raw, stored', [
    ('thomas', 'Thomas'),
    ('  thomas   feinberg ', 'Thomas Feinberg'),
    ('mary-jane', 'Mary-Jane'),
    ("o'neil", "O'Neil"),
    ('McDonald', 'McDonald'),
    ('van der Berg', 'van der Berg'),
    ('DE LA CRUZ', 'DE LA CRUZ'),
    ('Thomas', 'Thomas'),
    ('élodie', 'Élodie'),
])
def test_names_are_title_cased_unless_capitals_were_typed(raw, stored):
    data = _valid(BillingContactInputSerializer(data=_contact(first_name=raw, last_name=raw)))

    assert (data['first_name'], data['last_name']) == (stored, stored)


@pytest.mark.parametrize('city, province, stored', [
    ('London, Ontario', 'ON', 'London'),
    ('London, ON', 'ON', 'London'),
    ('london, ontario', 'on', 'london'),
    ('London,Ontario', 'ON', 'London'),
    ('London, Ontario', 'BC', 'London, Ontario'),
    ('London Ontario', 'ON', 'London Ontario'),
    ('  Ottawa  ', 'ON', 'Ottawa'),
    ('Victoria, British Columbia', 'BC', 'Victoria'),
])
def test_city_drops_only_the_province_that_is_set(city, province, stored):
    data = _valid(BillingContactInputSerializer(data=_contact(city=city, province=province)))

    assert data['city'] == stored


@pytest.mark.parametrize('raw', ['n6a1b2', 'N6A 1B2', ' n6a 1b2 '])
def test_postal_code_is_stored_a1a_1a1(raw):
    assert _valid(BillingContactInputSerializer(data=_contact(postal_code=raw)))['postal_code'] == 'N6A 1B2'


def test_bad_postal_code_is_rejected():
    serializer = BillingContactInputSerializer(data=_contact(postal_code='12345'))

    assert not serializer.is_valid()
    assert 'postal_code' in serializer.errors


def test_email_is_trimmed_and_lowercased():
    assert _valid(BillingContactInputSerializer(data=_contact(email=' Pat@Parent.COM ')))['email'] == 'pat@parent.com'


@pytest.mark.django_db
def test_student_create_normalizes_its_own_fields():
    data = _valid(StudentCreateSerializer(data={
        'email': 'New@Student.com', 'first_name': 'new', 'last_name': 'student',
        'phone_number': '(416) 822-8104', 'billing_contact': _contact(city='Toronto, ON'),
    }))

    assert (data['email'], data['first_name'], data['last_name'], data['phone_number']) == (
        'new@student.com', 'New', 'Student', '4168228104'
    )
    assert data['billing_contact']['city'] == 'Toronto'


@pytest.mark.django_db
def test_student_create_allows_a_blank_phone():
    data = _valid(StudentCreateSerializer(data={
        'email': 'new@student.com', 'first_name': 'New', 'last_name': 'Student',
        'phone_number': '', 'billing_contact': _contact(),
    }))

    assert data['phone_number'] == ''


@pytest.mark.django_db
def test_contact_partial_update_reads_the_stored_province(student_user, school):
    from billing.models import BillableContact

    contact = BillableContact.objects.create(student=student_user, school=school, **_contact(), is_primary=True)
    data = _valid(BillableContactSerializer(contact, data={'city': 'Toronto, Ontario'}, partial=True))

    assert data['city'] == 'Toronto'


@pytest.mark.django_db
def test_teacher_update_allows_blank_phone_and_postal(teacher_user):
    data = _valid(TeacherUpdateSerializer(
        teacher_user, data={'phone_number': '', 'postal_code': ''}, partial=True,
    ))

    assert (data['phone_number'], data['postal_code']) == ('', '')


@pytest.mark.django_db
def test_teacher_city_without_a_province_is_kept(teacher_user):
    teacher_user.province = ''
    teacher_user.save()
    data = _valid(TeacherUpdateSerializer(teacher_user, data={'city': 'London, Ontario'}, partial=True))

    assert data['city'] == 'London, Ontario'


@pytest.mark.django_db
def test_school_phone_rejects_short_numbers(school):
    serializer = SchoolSerializer(school, data={'phone_number': '555-0100'}, partial=True)

    assert not serializer.is_valid()
    assert serializer.errors['phone_number'] == [PHONE_ERROR]
