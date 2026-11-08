"""
Integration tests for management API endpoints.

Tests cover:
- Global rate settings CRUD operations
- Teacher management and rate updates
- Permission enforcement (management-only)
- Rate locking mechanism (existing lessons unchanged)
"""

import re
from datetime import date, time
from decimal import Decimal, ROUND_HALF_UP

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken
from billing.models import (
    BatchLessonItem, GlobalRateSettings, Lesson, Invoice, MonthlyInvoiceBatch,
)
from django.contrib.auth import get_user_model
from faker import Faker

User = get_user_model()

# MAP-250: the frontend's MoneyStringSchema (ZOD-DISCOVERY §3).
MONEY_RE = re.compile(r'^(?:0|[1-9]\d{0,7})\.\d{2}$')


@pytest.mark.django_db
class TestDeleteRejectedBatch:
    """management_delete_rejected_batch — only rejected, never-invoiced batches may be deleted."""

    def _batch(self, teacher, **kwargs):
        defaults = dict(
            teacher=teacher, school=teacher.school, month=7, year=2026, status='draft'
        )
        defaults.update(kwargs)
        return MonthlyInvoiceBatch.objects.create(**defaults)

    def test_delete_rejected_batch_succeeds(self, authenticated_management_client, teacher_user):
        batch = self._batch(teacher_user, status='draft', rejection_reason='Fix dates')
        url = reverse('management_delete_rejected_batch', args=[batch.id])
        response = authenticated_management_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not MonthlyInvoiceBatch.objects.filter(id=batch.id).exists()

    def test_delete_approved_batch_blocked(self, authenticated_management_client, teacher_user):
        batch = self._batch(teacher_user, status='approved')
        url = reverse('management_delete_rejected_batch', args=[batch.id])
        response = authenticated_management_client.delete(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert MonthlyInvoiceBatch.objects.filter(id=batch.id).exists()

    def test_delete_plain_draft_blocked(self, authenticated_management_client, teacher_user):
        # Draft with no rejection_reason is not a rejected batch — must not delete.
        batch = self._batch(teacher_user, status='draft', rejection_reason='')
        url = reverse('management_delete_rejected_batch', args=[batch.id])
        response = authenticated_management_client.delete(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert MonthlyInvoiceBatch.objects.filter(id=batch.id).exists()

    def test_delete_as_teacher_forbidden(self, authenticated_teacher_client, teacher_user):
        batch = self._batch(teacher_user, status='draft', rejection_reason='Fix dates')
        url = reverse('management_delete_rejected_batch', args=[batch.id])
        response = authenticated_teacher_client.delete(url)
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert MonthlyInvoiceBatch.objects.filter(id=batch.id).exists()

    def test_rejected_list_excludes_plain_drafts(self, authenticated_management_client, teacher_user):
        """The Rejected tab must list only genuinely-rejected drafts (non-empty
        rejection_reason), not every fresh draft — and every listed batch is deletable."""
        rejected = self._batch(teacher_user, month=5, status='draft', rejection_reason='Fix dates')
        self._batch(teacher_user, month=6, status='draft', rejection_reason='')  # plain draft

        url = reverse('management_rejected_batches')
        response = authenticated_management_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        ids = [b['id'] for b in response.data]
        assert ids == [rejected.id]


@pytest.fixture
def api_client():
    """Create an API client for testing."""
    return APIClient()


@pytest.fixture
def authenticated_management_client(api_client, management_user):
    """Create an authenticated API client with management user."""
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.fixture
def authenticated_teacher_client(api_client, teacher_user):
    """Create an authenticated API client with teacher user."""
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def global_rates(db):
    """Create or get global rate settings."""
    return GlobalRateSettings.get_settings()


@pytest.mark.django_db
class TestGlobalRateSettingsAPI:
    """Tests for /api/billing/management/global-rates/ endpoint."""

    def test_get_global_rates_as_management(self, authenticated_management_client, global_rates):
        """Management can retrieve global rate settings."""
        url = reverse('global_rate_settings')
        response = authenticated_management_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert 'online_teacher_rate' in response.data
        assert 'online_student_rate' in response.data
        assert 'inperson_student_rate' in response.data
        assert response.data['online_teacher_rate'] == '45.00'

    def test_get_global_rates_as_teacher_forbidden(self, authenticated_teacher_client):
        """Teachers cannot access global rate settings."""
        url = reverse('global_rate_settings')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_global_rates_unauthenticated(self, api_client):
        """Unauthenticated users cannot access global rate settings."""
        url = reverse('global_rate_settings')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_global_rates_as_management(self, authenticated_management_client, global_rates, management_user):
        """Management can update global rate settings."""
        url = reverse('global_rate_settings')
        data = {
            'online_teacher_rate': '50.00',
            'online_student_rate': '65.00',
            'inperson_student_rate': '110.00'
        }
        response = authenticated_management_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['online_teacher_rate'] == '50.00'
        assert response.data['online_student_rate'] == '65.00'
        assert response.data['inperson_student_rate'] == '110.00'
        assert response.data['updated_by'] == management_user.id
        assert response.data['updated_by_name'] == 'Test Manager'

    def test_update_global_rates_as_teacher_forbidden(self, authenticated_teacher_client):
        """Teachers cannot update global rate settings."""
        url = reverse('global_rate_settings')
        data = {'online_teacher_rate': '100.00'}
        response = authenticated_teacher_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_update_global_rates_partial(self, authenticated_management_client, global_rates):
        """Management can partially update global rate settings."""
        url = reverse('global_rate_settings')
        data = {'online_teacher_rate': '55.00'}
        response = authenticated_management_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['online_teacher_rate'] == '55.00'
        # Other rates should remain unchanged
        assert response.data['online_student_rate'] == '60.00'


@pytest.mark.django_db
class TestTeacherManagementAPI:
    """Tests for /api/billing/management/teachers/ endpoints."""

    def test_list_teachers_as_management(self, authenticated_management_client, teacher_user):
        """Management can list all teachers with stats."""
        url = reverse('management_teacher_list')
        response = authenticated_management_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1
        teacher_data = response.data[0]
        assert teacher_data['email'] == teacher_user.email
        assert teacher_data['hourly_rate'] == '80.00'
        assert 'total_students' in teacher_data
        assert 'total_lessons' in teacher_data
        assert 'total_earnings' in teacher_data

    def test_list_teachers_as_teacher_forbidden(self, authenticated_teacher_client):
        """Teachers cannot list other teachers."""
        url = reverse('management_teacher_list')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_teacher_detail_as_management(self, authenticated_management_client, teacher_user):
        """Management can retrieve teacher details."""
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        response = authenticated_management_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['email'] == teacher_user.email
        assert response.data['hourly_rate'] == '80.00'
        assert 'total_students' in response.data
        assert 'recent_lessons' in response.data

    # MAP-293 B: the tally is the active assigned-student set, the same set
    # the teacher's students page lists.

    def _assign_students(self, teacher, count, is_active=True):
        students = []
        for i in range(count):
            student = User.objects.create_user(
                email=f"assigned{'' if is_active else '-inactive'}{i}@test.com",
                user_type='student',
                first_name='Assigned',
                last_name=f'Student{i}',
                school=teacher.school,
                is_approved=True,
                is_active=is_active,
            )
            student.assigned_teachers.add(teacher)
            students.append(student)
        return students

    def _list_row(self, client, teacher):
        response = client.get(reverse('management_teacher_list'))
        assert response.status_code == status.HTTP_200_OK
        return next(row for row in response.data if row['id'] == teacher.id)

    def test_list_total_students_counts_active_assigned_without_lessons(
        self, authenticated_management_client, teacher_user
    ):
        """Assigned students with no lessons yet are counted."""
        self._assign_students(teacher_user, 2)

        row = self._list_row(authenticated_management_client, teacher_user)

        assert row['total_students'] == 2

    def test_total_students_excludes_inactive_and_unassigned(
        self, authenticated_management_client, teacher_user, student_user
    ):
        """An inactive assigned student and a taught-but-unassigned student are not counted."""
        # student_user has a completed lesson with teacher_user but is not assigned.
        assert not student_user.assigned_teachers.filter(pk=teacher_user.pk).exists()
        self._assign_students(teacher_user, 1)
        self._assign_students(teacher_user, 1, is_active=False)

        row = self._list_row(authenticated_management_client, teacher_user)
        detail = authenticated_management_client.get(
            reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        )

        assert row['total_students'] == 1
        assert detail.data['total_students'] == 1

    def test_detail_total_students_counts_active_assigned(
        self, authenticated_management_client, teacher_user
    ):
        """The detail serializer uses the same active assigned set."""
        self._assign_students(teacher_user, 3)

        response = authenticated_management_client.get(
            reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['total_students'] == 3

    def test_total_students_is_active_subset_of_teacher_students_endpoint(
        self, authenticated_management_client, teacher_user, student_user
    ):
        """The teacher's students page lists every non-removed assigned student;
        the tally counts only the active (billable) ones (MAP-302, owner Q1 b)."""
        assigned = self._assign_students(teacher_user, 2)
        waitlisted = assigned[1]
        waitlisted.status = 'waitlist'
        waitlisted.save(update_fields=['status'])
        self._assign_students(teacher_user, 1, is_active=False)

        row = self._list_row(authenticated_management_client, teacher_user)
        page = authenticated_management_client.get(
            reverse('teacher_students', kwargs={'teacher_id': teacher_user.id})
        )

        assert page.status_code == status.HTTP_200_OK
        listed_ids = {s['id'] for s in page.data['students']}
        assert listed_ids == {s.id for s in assigned}
        active_listed = {s['id'] for s in page.data['students'] if s['status'] == 'active'}
        assert active_listed == {assigned[0].id}
        assert row['total_students'] == len(active_listed) == page.data['total_students']

    def test_update_teacher_rate_as_management(self, authenticated_management_client, teacher_user):
        """Management can update teacher hourly rate."""
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        data = {'hourly_rate': '90.00'}
        response = authenticated_management_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['hourly_rate'] == '90.00'

        # Verify database update
        teacher_user.refresh_from_db()
        assert teacher_user.hourly_rate == Decimal('90.00')

    def test_update_teacher_rate_as_teacher_forbidden(self, authenticated_teacher_client, teacher_user):
        """Teachers cannot update their own hourly rate."""
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        data = {'hourly_rate': '150.00'}
        response = authenticated_teacher_client.patch(url, data, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestMoneyTotalsWireFormat:
    """MAP-250: computed money totals reach the browser as 2dp decimal strings, never JSON numbers.

    Assertions read the rendered body (response.json()), because response.data still
    holds the Decimal objects that DRF's encoder would turn into floats.
    """

    def _cents(self, value):
        # Postgres numeric(10,2) rounds half away from zero; the wire must agree with storage.
        return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def _batch_with_sub_cent_items(self, teacher, student):
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher, school=teacher.school, month=6, year=2026, status='submitted'
        )
        for day in (1, 8):
            BatchLessonItem.objects.create(
                batch=batch,
                student=student,
                scheduled_date=date(2026, 6, day),
                start_time=time(10, 0),
                duration=Decimal('0.75'),
                lesson_type='online',
                teacher_rate=Decimal('45.55'),
                student_rate=Decimal('60.55'),
                status='completed',
            )
        return batch

    def _paid_invoice(self, teacher, amount, invoice_status):
        return Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=teacher,
            school=teacher.school,
            status=invoice_status,
            total_amount=amount,
            payment_balance=amount,
        )

    def test_batch_detail_totals_are_2dp_strings(
        self, authenticated_management_client, teacher_user, student_user
    ):
        batch = self._batch_with_sub_cent_items(teacher_user, student_user)
        items = list(batch.lesson_items.all())
        teacher_total = sum(i.calculate_teacher_payment() for i in items)
        student_total = sum(i.calculate_student_charge() for i in items)
        # Precondition: the raw sums carry more than 2 decimal places.
        assert teacher_total != self._cents(teacher_total)
        assert student_total != self._cents(student_total)

        response = authenticated_management_client.get(
            reverse('management_batch_detail', args=[batch.id])
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        for key, raw in (
            ('total_teacher_payment', teacher_total),
            ('total_student_charges', student_total),
        ):
            assert isinstance(body[key], str)
            assert MONEY_RE.match(body[key])
            assert Decimal(body[key]) == self._cents(raw)

    def test_empty_batch_totals_are_zero_strings(
        self, authenticated_management_client, teacher_user
    ):
        batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=teacher_user.school, month=6, year=2026, status='draft'
        )

        body = authenticated_management_client.get(
            reverse('management_batch_detail', args=[batch.id])
        ).json()

        assert body['total_teacher_payment'] == '0.00'
        assert body['total_student_charges'] == '0.00'

    def test_teacher_list_total_earnings_is_2dp_string(
        self, authenticated_management_client, teacher_user
    ):
        url = reverse('management_teacher_list')
        before = next(
            t for t in authenticated_management_client.get(url).json()
            if t['id'] == teacher_user.id
        )
        assert before['total_earnings'] == '0.00'

        approved = self._paid_invoice(teacher_user, Decimal('630.00'), 'approved')
        paid = self._paid_invoice(teacher_user, Decimal('510.50'), 'paid')

        after = next(
            t for t in authenticated_management_client.get(url).json()
            if t['id'] == teacher_user.id
        )
        assert isinstance(after['total_earnings'], str)
        assert MONEY_RE.match(after['total_earnings'])
        assert Decimal(after['total_earnings']) == approved.payment_balance + paid.payment_balance

    def test_teacher_detail_total_earnings_is_2dp_string(
        self, authenticated_management_client, teacher_user
    ):
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        assert authenticated_management_client.get(url).json()['total_earnings'] == '0.00'

        invoice = self._paid_invoice(teacher_user, Decimal('1260.00'), 'approved')

        body = authenticated_management_client.get(url).json()
        assert isinstance(body['total_earnings'], str)
        assert MONEY_RE.match(body['total_earnings'])
        assert Decimal(body['total_earnings']) == invoice.payment_balance

    def test_school_detail_invoice_total_is_2dp_string(
        self, authenticated_management_client, teacher_user
    ):
        url = reverse('get_current_school')
        assert authenticated_management_client.get(url).json()['invoice_total'] == '0.00'

        approved = self._paid_invoice(teacher_user, Decimal('8000.00'), 'approved')
        paid = self._paid_invoice(teacher_user, Decimal('762.50'), 'paid')

        body = authenticated_management_client.get(url).json()
        assert isinstance(body['invoice_total'], str)
        assert MONEY_RE.match(body['invoice_total'])
        assert Decimal(body['invoice_total']) == approved.payment_balance + paid.payment_balance


@pytest.mark.django_db
class TestRateLockingMechanism:
    """Tests for rate locking - existing lessons should not be affected by rate changes."""

    def test_global_rate_change_does_not_affect_existing_online_lessons(
        self, authenticated_management_client, teacher_user, student_user, global_rates
    ):
        """Changing global online rates does not affect existing online lessons."""
        # Create an online lesson with current rate
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=teacher_user.school,
            duration=Decimal("1.0"),
            lesson_type="online",
            teacher_rate=Decimal("45.00"),  # Locked rate
            student_rate=Decimal("60.00"),
            status="completed"
        )
        original_teacher_rate = lesson.teacher_rate

        # Update global online teacher rate
        url = reverse('global_rate_settings')
        data = {'online_teacher_rate': '55.00'}
        response = authenticated_management_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Verify existing lesson rate unchanged (rate locking)
        lesson.refresh_from_db()
        assert lesson.teacher_rate == original_teacher_rate
        assert lesson.teacher_rate == Decimal("45.00")

    def test_teacher_rate_change_does_not_affect_existing_inperson_lessons(
        self, authenticated_management_client, teacher_user, student_user
    ):
        """Changing teacher hourly rate does not affect existing in-person lessons."""
        # Create an in-person lesson with current teacher rate
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=teacher_user.school,
            duration=Decimal("1.0"),
            lesson_type="in_person",
            teacher_rate=Decimal("80.00"),  # Locked at teacher's hourly_rate
            student_rate=Decimal("100.00"),
            status="completed"
        )
        original_teacher_rate = lesson.teacher_rate

        # Update teacher hourly rate
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        data = {'hourly_rate': '95.00'}
        response = authenticated_management_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Verify existing lesson rate unchanged (rate locking)
        lesson.refresh_from_db()
        assert lesson.teacher_rate == original_teacher_rate
        assert lesson.teacher_rate == Decimal("80.00")

    def test_global_rate_settings_endpoint_accepts_update(
        self, authenticated_management_client, teacher_user, student_user
    ):
        """
        The global_rate_settings endpoint accepts a PATCH and returns 200.

        Note: /management/global-rates/ routes to the school_settings view and updates
        SchoolSettings for the management user's school. Lesson.save() uses
        SchoolSettings.get_settings_for_school(), so the patched rate is reflected
        in new lessons created for teachers in that school.
        """
        url = reverse('global_rate_settings')
        data = {'online_teacher_rate': '50.00'}
        response = authenticated_management_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Create a new online lesson — SchoolSettings governs auto-rate assignment
        # and was just updated to 50.00, so the lesson reflects that.
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=teacher_user.school,
            duration=Decimal("1.0"),
            lesson_type="online",
            status="completed"
        )

        # Lesson.save() auto-assigns from SchoolSettings (updated to 50.00 by the PATCH above).
        assert lesson.teacher_rate == Decimal("50.00")
        assert lesson.student_rate == Decimal("60.00")

    def test_new_inperson_lesson_uses_updated_teacher_rate(
        self, authenticated_management_client, teacher_user, student_user
    ):
        """New in-person lessons use the updated teacher hourly rate."""
        # Update teacher hourly rate
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        data = {'hourly_rate': '100.00'}
        response = authenticated_management_client.patch(url, data, format='json')
        assert response.status_code == status.HTTP_200_OK

        # Refresh teacher data
        teacher_user.refresh_from_db()

        # Create a new in-person lesson (rates auto-set in Lesson.save() from defaults)
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            school=teacher_user.school,
            duration=Decimal("1.0"),
            lesson_type="in_person",
            status="completed"
        )

        # Lesson.save() should have set teacher_rate to teacher's new hourly_rate
        assert lesson.teacher_rate == Decimal("100.00")


@pytest.mark.django_db
class TestPhase2BillableContactSchoolScoping:
    """SEC-07: manage_billable_contact must filter by school=request.user.school."""

    def test_manage_billable_contact_rejects_cross_school(
        self, api_client, management_user, second_school
    ):
        """
        SEC-07: Management from school A cannot GET billable contact from school B.
        """
        from billing.models import BillableContact

        school2_student = User.objects.create_user(
            email="student_s2_contact@test.com", password="test123",
            user_type="student", school=second_school, is_approved=True
        )
        contact = BillableContact.objects.create(
            student=school2_student,
            school=second_school,
            contact_type='parent',
            first_name='Cross', last_name='School',
            email='cross@school2.com', phone='416-555-1234',
            street_address='1 Other St', city='Vancouver',
            province='BC', postal_code='V6B 1A1',
            is_primary=True
        )

        api_client.force_authenticate(user=management_user)
        url = reverse('manage_billable_contact', kwargs={'pk': contact.id})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# MAP-177: UserSerializer never writes privileged columns or the password.
# ---------------------------------------------------------------------------

PRIVILEGED_COLUMNS = ('user_type', 'school_id', 'is_approved', 'is_active', 'is_staff', 'is_superuser')


def _snapshot(user):
    user.refresh_from_db()
    return {c: getattr(user, c) for c in PRIVILEGED_COLUMNS} | {'password': user.password}


def _escalation_payload(other_school):
    return {
        'user_type': 'management',
        'school': other_school.id,
        'is_approved': False,
        'is_active': False,
        'is_staff': True,
        'is_superuser': True,
        'password': 'Hijack!123',
    }


@pytest.mark.django_db
class TestManagementPutsCannotEscalate:
    """MAP-177 acceptance: the two management PUTs ignore privileged keys and password."""

    def test_update_teacher_ignores_privileged_keys(
        self, authenticated_management_client, teacher_user, second_school
    ):
        before = _snapshot(teacher_user)
        url = reverse('management_update_teacher', kwargs={'pk': teacher_user.id})

        response = authenticated_management_client.put(
            url, _escalation_payload(second_school) | {'hourly_rate': '95.00', 'bio': 'Updated bio'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert _snapshot(teacher_user) == before
        assert teacher_user.hourly_rate == Decimal('95.00')
        assert teacher_user.bio == 'Updated bio'
        assert teacher_user.check_password('Hijack!123') is False

    def test_update_student_ignores_privileged_keys(
        self, authenticated_management_client, student_user, second_school
    ):
        before = _snapshot(student_user)
        url = reverse('management_student_detail', kwargs={'pk': student_user.id})

        response = authenticated_management_client.put(
            url, _escalation_payload(second_school) | {'phone_number': '4165550199', 'address': '1 New St'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert _snapshot(student_user) == before
        assert student_user.phone_number == '4165550199'
        assert student_user.address == '1 New St'
        assert student_user.check_password('Hijack!123') is False

    @pytest.mark.parametrize('route,fixture', [
        ('management_update_teacher', 'teacher_user'),
        ('management_student_detail', 'student_user'),
    ])
    def test_put_with_password_leaves_hash_unchanged(
        self, request, authenticated_management_client, route, fixture
    ):
        user = request.getfixturevalue(fixture)
        hash_before = user.password
        assert user.check_password('testpass123') is True

        response = authenticated_management_client.put(
            reverse(route, kwargs={'pk': user.id}),
            {'password': 'Hijack!123', 'first_name': 'Renamed'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.password == hash_before
        assert user.check_password('testpass123') is True
        assert user.first_name == 'Renamed'

    @pytest.mark.parametrize('route,fixture', [
        ('management_update_teacher', 'teacher_user'),
        ('management_student_detail', 'student_user'),
    ])
    def test_fuzz_every_user_field_only_profile_fields_change(
        self, request, authenticated_management_client, teacher_user, second_school, route, fixture
    ):
        """Faker payload carrying every concrete User field name: only the
        writable, non-privileged profile fields may change."""
        user = request.getfixturevalue(fixture)
        fake = Faker()
        Faker.seed(177)

        def fake_value(field):
            kind = field.get_internal_type()
            if field.name == 'email':
                return fake.email()
            if field.name == 'hourly_rate':
                return str(fake.pydecimal(left_digits=3, right_digits=2, positive=True))
            if field.name == 'phone_number':
                return fake.numerify('##########')  # MAP-293: stored phones are 10 digits
            if field.name == 'province':
                return fake.random_element([code for code, _ in User.PROVINCES])
            if field.name == 'status':  # MAP-302: a choice field, like province
                return fake.random_element([value for value, _ in User.STUDENT_STATUSES])
            if field.name == 'postal_code':
                return fake.bothify('?#? #?#', letters='ABCEGHJKLMNPRSTVXY')
            if field.name == 'school':
                return second_school.id
            if field.name == 'assigned_teachers':
                return [teacher_user.id]
            if kind in ('ManyToManyField',):
                return []
            if kind == 'ForeignKey':
                return fake.pyint()
            if kind == 'BooleanField':
                return fake.pybool()
            if kind in ('DateTimeField', 'DateField'):
                return fake.iso8601()
            if kind in ('DecimalField', 'IntegerField', 'AutoField', 'BigAutoField'):
                return fake.pyint()
            return fake.pystr(max_chars=min(field.max_length or 40, 40))

        payload = {f.name: fake_value(f) for f in User._meta.get_fields() if f.concrete}
        payload.update(_escalation_payload(second_school))
        assert {'id', 'password', 'is_staff', 'is_superuser', 'oauth_provider', 'date_joined'} <= payload.keys()

        before = _snapshot(user)
        untouched_before = (user.id, user.oauth_provider, user.oauth_id, user.date_joined, user.last_login)

        response = authenticated_management_client.put(reverse(route, kwargs={'pk': user.id}), payload, format='json')

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _snapshot(user) == before
        assert (user.id, user.oauth_provider, user.oauth_id, user.date_joined, user.last_login) == untouched_before
        for name in ('email', 'first_name', 'last_name', 'phone_number', 'address', 'bio'):
            assert getattr(user, name) == payload[name], name
        assert user.hourly_rate == Decimal(payload['hourly_rate'])
        assert set(user.assigned_teachers.values_list('id', flat=True)) == {teacher_user.id}


# ---------------------------------------------------------------------------
# MAP-265 — contact and schedule PUTs never move a row to another student or school
# ---------------------------------------------------------------------------

from billing.models import BillableContact as _Contact, RecurringLessonsSchedule as _Schedule


def _contact_body(**extra):
    return {
        'contact_type': 'parent',
        'first_name': 'Pat', 'last_name': 'Parent',
        'email': 'pat@parent.com', 'phone': '416-555-0100',
        'street_address': '1 Main St', 'city': 'Toronto',
        'province': 'ON', 'postal_code': 'M5H 2N2',
        'is_primary': True,
    } | extra


def _student(school, email):
    return User.objects.create_user(
        email=email, password='testpass123', user_type='student',
        first_name='Other', last_name='Student', school=school, is_approved=True,
    )


@pytest.fixture
def contact(student_user, school):
    return _Contact.objects.create(student=student_user, school=school, **_contact_body())


@pytest.fixture
def schedule(student_user, teacher_user, school):
    student_user.assigned_teachers.add(teacher_user)
    return _Schedule.objects.create(
        teacher=teacher_user, student=student_user, school=school,
        day_of_week=2, start_time=time(15, 0), duration=Decimal('1.0'),
        lesson_type='in_person', is_active=True, start_date=date(2026, 1, 7),
        created_by=teacher_user,
    )


@pytest.mark.django_db
class TestContactAndSchedulePutsKeepParent:
    """MAP-265 acceptance: `student`/`school` on a management PUT are ignored
    (200, row unchanged); the create routes still bind the URL student."""

    def test_contact_put_ignores_student_and_school(
        self, authenticated_management_client, contact, student_user, school, second_school
    ):
        other = _student(school, 'other_same_school@test.com')

        response = authenticated_management_client.put(
            reverse('manage_billable_contact', kwargs={'pk': contact.id}),
            {'student': other.id, 'school': second_school.id, 'first_name': 'Renamed', 'is_primary': True},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        contact.refresh_from_db()
        assert contact.student_id == student_user.id
        assert contact.school_id == school.id
        assert contact.first_name == 'Renamed'
        assert response.data['student'] == student_user.id
        assert response.data['school'] == school.id

    def test_contact_put_cross_school_school_never_written(
        self, authenticated_management_client, contact, school, second_school
    ):
        response = authenticated_management_client.put(
            reverse('manage_billable_contact', kwargs={'pk': contact.id}),
            {'school': second_school.id, 'is_primary': True},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        contact.refresh_from_db()
        assert contact.school_id == school.id
        assert not _Contact.objects.filter(school=second_school).exists()

    @pytest.mark.parametrize('other_in_second_school', [False, True], ids=['same_school', 'cross_school'])
    def test_schedule_put_ignores_student(
        self, authenticated_management_client, schedule, student_user, school, second_school,
        other_in_second_school,
    ):
        other = _student(second_school if other_in_second_school else school, 'other_sched@test.com')

        response = authenticated_management_client.put(
            reverse('recurring_schedule_detail', args=[student_user.id, schedule.id]),
            {'student': other.id, 'start_time': '16:00'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        schedule.refresh_from_db()
        assert schedule.student_id == student_user.id
        assert schedule.start_time == time(16, 0)
        assert response.data['student'] == student_user.id
        assert not _Schedule.objects.filter(student=other).exists()

    def test_schedule_put_cross_school_school_never_written(
        self, authenticated_management_client, schedule, student_user, school, second_school
    ):
        response = authenticated_management_client.put(
            reverse('recurring_schedule_detail', args=[student_user.id, schedule.id]),
            {'school': second_school.id, 'start_time': '16:00'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        schedule.refresh_from_db()
        assert schedule.school_id == school.id
        assert not _Schedule.objects.filter(school=second_school).exists()

    def test_contact_create_binds_url_student_and_school(
        self, authenticated_management_client, student_user, school, second_school
    ):
        other = _student(school, 'other_create@test.com')

        response = authenticated_management_client.post(
            reverse('add_billable_contact', kwargs={'student_id': student_user.id}),
            _contact_body(student=other.id, school=second_school.id),
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        created = _Contact.objects.get(pk=response.data['id'])
        assert created.student_id == student_user.id
        assert created.school_id == school.id

    def test_schedule_create_binds_url_student(
        self, authenticated_management_client, student_user, teacher_user, school
    ):
        student_user.assigned_teachers.add(teacher_user)
        other = _student(school, 'other_sched_create@test.com')

        response = authenticated_management_client.post(
            reverse('student_recurring_schedules', args=[student_user.id]),
            {
                'teacher': teacher_user.id, 'student': other.id,
                'day_of_week': 2, 'start_time': '15:00', 'duration': '1.0',
                'lesson_type': 'in_person', 'start_date': '2026-01-07',
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        created = _Schedule.objects.get(pk=response.data['id'])
        assert created.student_id == student_user.id
        assert created.school_id == school.id


# ---------------------------------------------------------------------------
# MAP-186 — approval and payroll generate post to the ledger
# ---------------------------------------------------------------------------

from datetime import date, time

from django.db import transaction as db_transaction

from billing.models import (
    BatchLessonItem,
    BillableContact,
    CreditTransaction,
    PreBillingInvoice,
    StudentCreditAccount,
)
from billing.services import ledger


def _funded_account(student, school, amount):
    """Fresh account funded through the ledger (a paid pre-billing invoice)."""
    account = StudentCreditAccount.objects.create(
        student=student, school=school, balance=Decimal('0.00'),
    )
    invoice = PreBillingInvoice.objects.create(
        student=student, school=school, status='paid', amount=amount,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
    )
    with db_transaction.atomic():
        ledger.post(account, type='pre_billing_payment', amount=amount, source_invoice=invoice)
    return account


def _ledger_contact(student, school):
    return BillableContact.objects.create(
        student=student, school=school, contact_type='parent',
        first_name='Ledger', last_name='Contact',
        email=f'ledger_{student.pk}@management.test', phone='416-555-0100',
        street_address='1 Ledger St', city='Toronto', province='ON',
        postal_code='M5H 2N2', is_primary=True,
    )


def _ledger_item(batch, student, school_settings, status='completed', day=15):
    """Item priced from the school's fixture rate — no literal amounts."""
    return BatchLessonItem.objects.create(
        batch=batch, student=student,
        scheduled_date=date(batch.year, batch.month, day), start_time=time(10, 0),
        duration=Decimal('1.0'), lesson_type='online',
        teacher_rate=school_settings.online_teacher_rate,
        student_rate=school_settings.online_student_rate,
        status=status,
    )


def _submitted_batch(teacher, school):
    return MonthlyInvoiceBatch.objects.create(
        teacher=teacher, school=school, month=6, year=2026, status='submitted',
    )


def _ledger_rows(account, tx_type):
    return CreditTransaction.objects.filter(account=account, type=tx_type)


def _invariant_holds(account):
    account.refresh_from_db()
    rows = CreditTransaction.objects.filter(account=account, legacy=False)
    up = sum((r.amount for r in rows if r.type in ('pre_billing_payment', 'waived_rollover')), Decimal('0.00'))
    down = sum((r.amount for r in rows if r.type == 'lesson_charge'), Decimal('0.00'))
    return account.balance == up - down


@pytest.mark.django_db
class TestApprovalLedger:
    """Approval charges completed and forfeited items alike; never clamps silently."""

    def _approve(self, client, batch):
        return client.post(reverse('management_approve_batch', kwargs={'batch_id': batch.id}))

    def _generate(self, client, batch):
        return client.post(
            reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id}),
            format='json',
        )

    def test_insufficient_balance_posts_charge_and_shortfall_and_flags(
        self, authenticated_management_client, teacher_user, student_user, school, school_settings,
    ):
        _ledger_contact(student_user, school)
        batch = _submitted_batch(teacher_user, school)
        item = _ledger_item(batch, student_user, school_settings)
        charge = item.student_rate * item.duration
        uncovered = (charge / 3).quantize(Decimal('0.01'))
        account = StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=charge - uncovered,
        )

        response = self._approve(authenticated_management_client, batch)

        assert response.status_code == 200, response.data
        lesson_charges = _ledger_rows(account, 'lesson_charge')
        shortfalls = _ledger_rows(account, 'shortfall')
        assert lesson_charges.count() == 1
        assert lesson_charges.get().amount == charge - uncovered
        assert lesson_charges.get().source_batch_item_id == item.id
        assert shortfalls.count() == 1
        assert shortfalls.get().amount == uncovered
        assert shortfalls.get().source_batch_item_id == item.id
        account.refresh_from_db()
        assert account.balance == Decimal('0.00')
        assert account.needs_attention is True

    def test_sufficient_balance_posts_only_lesson_charge(
        self, authenticated_management_client, teacher_user, student_user, school, school_settings,
    ):
        _ledger_contact(student_user, school)
        batch = _submitted_batch(teacher_user, school)
        item = _ledger_item(batch, student_user, school_settings)
        charge = item.student_rate * item.duration
        surplus = (charge / 2).quantize(Decimal('0.01'))
        account = StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=charge + surplus,
        )

        response = self._approve(authenticated_management_client, batch)

        assert response.status_code == 200, response.data
        assert _ledger_rows(account, 'lesson_charge').count() == 1
        assert _ledger_rows(account, 'lesson_charge').get().amount == charge
        assert _ledger_rows(account, 'shortfall').count() == 0
        account.refresh_from_db()
        assert account.balance == surplus
        assert account.needs_attention is False

    def test_every_approval_row_has_a_source_and_none_is_legacy(
        self, authenticated_management_client, teacher_user, student_user, school, school_settings,
    ):
        _ledger_contact(student_user, school)
        batch = _submitted_batch(teacher_user, school)
        _ledger_item(batch, student_user, school_settings, day=1)
        _ledger_item(batch, student_user, school_settings, status='forfeited', day=8)
        account = StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=Decimal('0.00'),
        )

        assert self._approve(authenticated_management_client, batch).status_code == 200

        rows = CreditTransaction.objects.filter(account=account)
        assert rows.exists()
        assert not rows.filter(legacy=True).exists()
        assert not rows.filter(source_batch_item__isnull=True).exists()

    def test_forfeited_item_charges_at_approval_without_forfeited_row(
        self, authenticated_management_client, teacher_user, student_user, school, school_settings,
    ):
        _ledger_contact(student_user, school)
        batch = _submitted_batch(teacher_user, school)
        item = _ledger_item(batch, student_user, school_settings, status='forfeited')
        charge = item.student_rate * item.duration
        account = StudentCreditAccount.objects.create(
            student=student_user, school=school, balance=charge,
        )

        response = self._approve(authenticated_management_client, batch)

        assert response.status_code == 200, response.data
        assert _ledger_rows(account, 'forfeited').count() == 0
        assert _ledger_rows(account, 'lesson_charge').count() == 1
        assert _ledger_rows(account, 'lesson_charge').get().source_batch_item_id == item.id
        account.refresh_from_db()
        assert account.balance == Decimal('0.00')

    def test_generate_posts_one_forfeited_row_per_item(
        self, authenticated_management_client, teacher_user, student_user, school, school_settings,
    ):
        _ledger_contact(student_user, school)
        batch = _submitted_batch(teacher_user, school)
        item = _ledger_item(batch, student_user, school_settings, status='forfeited')
        account = _funded_account(student_user, school, item.student_rate * item.duration)
        assert self._approve(authenticated_management_client, batch).status_code == 200
        balance_after_approval = StudentCreditAccount.objects.get(pk=account.pk).balance

        response = self._generate(authenticated_management_client, batch)

        assert response.status_code == 200, response.data
        assert response.data['forfeited_credits_written'] == 1
        forfeited = _ledger_rows(account, 'forfeited')
        assert forfeited.count() == 1
        assert forfeited.get().source_batch_item_id == item.id
        account.refresh_from_db()
        assert account.balance == balance_after_approval  # informational: balance untouched
        assert _invariant_holds(account)

    def test_generate_twice_keeps_one_forfeited_row(
        self, authenticated_management_client, teacher_user, student_user, school, school_settings,
    ):
        _ledger_contact(student_user, school)
        batch = _submitted_batch(teacher_user, school)
        item = _ledger_item(batch, student_user, school_settings, status='forfeited')
        account = _funded_account(student_user, school, item.student_rate * item.duration)
        assert self._approve(authenticated_management_client, batch).status_code == 200
        assert self._generate(authenticated_management_client, batch).status_code == 200

        second = self._generate(authenticated_management_client, batch)

        assert second.status_code == 409  # invoice already generated for this batch
        assert _ledger_rows(account, 'forfeited').count() == 1
        assert _ledger_rows(account, 'forfeited').get().source_batch_item_id == item.id
        assert _invariant_holds(account)

    def test_generate_does_not_repost_forfeited_for_an_item_already_recorded(
        self, authenticated_management_client, teacher_user, student_user, school, school_settings,
    ):
        """Dedup is keyed on the batch item, not the amount."""
        _ledger_contact(student_user, school)
        batch = _submitted_batch(teacher_user, school)
        recorded = _ledger_item(batch, student_user, school_settings, status='forfeited', day=1)
        fresh = _ledger_item(batch, student_user, school_settings, status='forfeited', day=8)
        account = StudentCreditAccount.objects.create(
            student=student_user, school=school,
            balance=(recorded.student_rate + fresh.student_rate) * recorded.duration,
        )
        assert self._approve(authenticated_management_client, batch).status_code == 200
        with db_transaction.atomic():
            ledger.post(account, type='forfeited', amount=recorded.student_rate * recorded.duration,
                        source_batch_item=recorded)

        response = self._generate(authenticated_management_client, batch)

        assert response.status_code == 200, response.data
        # Same amount as `recorded`, different item → still written once for `fresh`.
        assert response.data['forfeited_credits_written'] == 1
        assert _ledger_rows(account, 'forfeited').filter(source_batch_item=recorded).count() == 1
        assert _ledger_rows(account, 'forfeited').filter(source_batch_item=fresh).count() == 1

    @pytest.mark.django_db(transaction=True)
    def test_concurrent_generate_creates_one_invoice_and_one_rollover_set(
        self, management_user, teacher_user, student_user, school, school_settings,
    ):
        """MAP-183: two generates racing on one approved batch → one payroll invoice,
        one waived_rollover row per charged waived item, one 200 and one 409."""
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connection

        _ledger_contact(student_user, school)
        batch = _submitted_batch(teacher_user, school)
        item = _ledger_item(batch, student_user, school_settings)
        account = _funded_account(student_user, school, item.student_rate * item.duration)
        client = APIClient()
        client.force_authenticate(user=management_user)
        assert self._approve(client, batch).status_code == 200
        # Waived after approval → charged at approval → refunded as rollover at generate.
        item.status = 'waived'
        item.save(update_fields=['status'])

        url = reverse('management_generate_teacher_invoice', kwargs={'batch_id': batch.id})
        user_id = management_user.id
        barrier = threading.Barrier(2)

        def _generate():
            connection.close()
            thread_client = APIClient()
            thread_client.force_authenticate(user=User.objects.get(id=user_id))
            barrier.wait(timeout=10)
            response = thread_client.post(url, format='json')
            connection.close()
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as ex:
            statuses = sorted(f.result(timeout=30) for f in [ex.submit(_generate), ex.submit(_generate)])

        assert statuses == [200, 409], statuses
        invoices = Invoice.objects.filter(teacher=teacher_user, invoice_type='teacher_payment')
        assert invoices.count() == 1
        batch.refresh_from_db()
        assert batch.invoice_id == invoices.get().id
        rollovers = _ledger_rows(account, 'waived_rollover')
        assert rollovers.count() == 1
        assert rollovers.get().source_batch_item_id == item.id
        assert _invariant_holds(account)


# ---------------------------------------------------------------------------
# MAP-141: management deactivation revokes the user's tokens
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDeactivationRevokesTokens:
    @staticmethod
    def _tokens(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        # Issued a few seconds before the deactivation (whole-second iat, D5).
        access['iat'] = int(access['iat']) - 5
        return str(access), str(refresh)

    @staticmethod
    def _assert_revoked(access, refresh):
        # A fresh, unauthenticated client: the management fixture
        # force-authenticates the shared api_client, which would mask the header.
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        assert client.get(reverse('user_profile')).status_code == status.HTTP_401_UNAUTHORIZED
        client.credentials()
        response = client.post(reverse('refresh_jwt_token'), {'refresh': refresh}, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_student_delete_revokes_tokens(self, authenticated_management_client, student_user):
        access, refresh = self._tokens(student_user)
        response = authenticated_management_client.delete(
            reverse('management_student_detail', kwargs={'pk': student_user.id})
        )
        assert response.status_code == status.HTTP_200_OK
        student_user.refresh_from_db()
        assert student_user.is_active is False
        assert student_user.password_changed_at is not None
        self._assert_revoked(access, refresh)

    def test_teacher_delete_revokes_tokens(self, authenticated_management_client, teacher_user):
        access, refresh = self._tokens(teacher_user)
        response = authenticated_management_client.delete(
            reverse('management_delete_teacher', kwargs={'pk': teacher_user.id})
        )
        assert response.status_code == status.HTTP_200_OK
        teacher_user.refresh_from_db()
        assert teacher_user.is_active is False
        assert teacher_user.password_changed_at is not None
        self._assert_revoked(access, refresh)


@pytest.mark.django_db
class TestRemovalReleasesEmail:
    """MAP-220: soft-deleting a user frees the address for reuse; the original
    stays readable in the rewritten email and in history; open payroll batches
    block teacher removal."""

    STUDENT_PAYLOAD = {
        'first_name': 'New', 'last_name': 'Student',
        'billing_contact': {
            'contact_type': 'parent', 'first_name': 'Parent', 'last_name': 'Name',
            'email': 'parent-reuse@test.com', 'phone': '416-555-0101',
            'street_address': '456 Main St', 'city': 'Toronto', 'province': 'ON',
            'postal_code': 'M4B 1B3',
        },
    }

    def test_delete_teacher_releases_email_and_allows_reuse(
        self, authenticated_management_client, teacher_user
    ):
        original = teacher_user.email
        refresh = RefreshToken.for_user(teacher_user)

        response = authenticated_management_client.delete(
            reverse('management_delete_teacher', kwargs={'pk': teacher_user.id})
        )

        assert response.status_code == status.HTTP_200_OK
        teacher_user.refresh_from_db()
        assert teacher_user.is_active is False
        assert teacher_user.email != original
        assert original.split('@')[0] in teacher_user.email
        assert str(teacher_user.id) in teacher_user.email
        assert teacher_user.history.first().email == teacher_user.email
        assert teacher_user.history.filter(email=original).exists()
        assert BlacklistedToken.objects.filter(token__jti=refresh['jti']).exists()

        created = authenticated_management_client.post(
            '/api/billing/management/students/',
            {**self.STUDENT_PAYLOAD, 'email': original}, format='json',
        )
        assert created.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(email=original, is_active=True).count() == 1

    def test_removed_teacher_is_not_listed_and_cannot_be_assigned(
        self, authenticated_management_client, teacher_user, student_user
    ):
        """The list feeds the assign-teacher picker; a removed teacher must drop
        out of it, and assigning one is refused."""
        authenticated_management_client.delete(
            reverse('management_delete_teacher', kwargs={'pk': teacher_user.id})
        )

        listed = authenticated_management_client.get(reverse('management_teacher_list'))
        assert listed.status_code == status.HTTP_200_OK
        assert teacher_user.id not in [t['id'] for t in listed.data]

        assigned = authenticated_management_client.post(
            reverse('assign_teachers_to_student', kwargs={'student_id': student_user.id}),
            {'teacher_ids': [teacher_user.id]}, format='json',
        )
        assert assigned.status_code == status.HTTP_400_BAD_REQUEST
        assert 'inactive' in assigned.data['error']
        assert not student_user.assigned_teachers.filter(pk=teacher_user.pk).exists()

    def test_delete_student_releases_email_and_allows_reuse(
        self, authenticated_management_client, student_user
    ):
        original = student_user.email

        response = authenticated_management_client.delete(
            reverse('management_student_detail', kwargs={'pk': student_user.id})
        )

        assert response.status_code == status.HTTP_200_OK
        student_user.refresh_from_db()
        assert student_user.is_active is False
        assert student_user.email != original
        assert original.split('@')[0] in student_user.email
        created = authenticated_management_client.post(
            '/api/billing/management/students/',
            {**self.STUDENT_PAYLOAD, 'email': original}, format='json',
        )
        assert created.status_code == status.HTTP_201_CREATED

    def test_delete_is_idempotent_on_the_email(self, authenticated_management_client, teacher_user):
        url = reverse('management_delete_teacher', kwargs={'pk': teacher_user.id})
        authenticated_management_client.delete(url)
        teacher_user.refresh_from_db()
        once = teacher_user.email

        authenticated_management_client.delete(url)

        teacher_user.refresh_from_db()
        assert teacher_user.email == once

    def test_delete_teacher_with_open_batch_returns_409_and_changes_nothing(
        self, authenticated_management_client, teacher_user, school
    ):
        original = teacher_user.email
        MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=9, year=2026, status='submitted',
        )
        MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=10, year=2026, status='draft',
        )
        MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=8, year=2026, status='approved',
        )

        response = authenticated_management_client.delete(
            reverse('management_delete_teacher', kwargs={'pk': teacher_user.id})
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert '2026-09' in response.data['error'] and '2026-10' in response.data['error']
        assert '2026-08' not in response.data['error']
        teacher_user.refresh_from_db()
        assert teacher_user.is_active is True
        assert teacher_user.email == original
        assert teacher_user.password_changed_at is None

    def test_delete_teacher_other_school_404(
        self, authenticated_management_client, teacher_user, second_school
    ):
        teacher_user.school = second_school
        teacher_user.save(update_fields=['school'])

        response = authenticated_management_client.delete(
            reverse('management_delete_teacher', kwargs={'pk': teacher_user.id})
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        teacher_user.refresh_from_db()
        assert teacher_user.is_active is True

    def test_create_with_a_pre_release_inactive_email_names_the_removed_account(
        self, authenticated_management_client, teacher_user
    ):
        # A row soft-deleted before MAP-220 still holds its address.
        teacher_user.is_active = False
        teacher_user.save(update_fields=['is_active'])

        created = authenticated_management_client.post(
            '/api/billing/management/students/',
            {**self.STUDENT_PAYLOAD, 'email': teacher_user.email}, format='json',
        )

        assert created.status_code == status.HTTP_400_BAD_REQUEST
        assert created.data['email'] == [
            f'This email belongs to a removed account (id {teacher_user.id})'
        ]

    def test_update_teacher_email_to_a_pre_release_inactive_email_names_the_removed_account(
        self, authenticated_management_client, teacher_user, student_user
    ):
        student_user.is_active = False
        student_user.save(update_fields=['is_active'])

        response = authenticated_management_client.put(
            reverse('management_update_teacher', kwargs={'pk': teacher_user.id}),
            {'email': student_user.email}, format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['email'] == [
            f'This email belongs to a removed account (id {student_user.id})'
        ]

    def test_update_teacher_email_to_an_active_email_is_a_plain_collision(
        self, authenticated_management_client, teacher_user, student_user
    ):
        response = authenticated_management_client.put(
            reverse('management_update_teacher', kwargs={'pk': teacher_user.id}),
            {'email': student_user.email}, format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'email' in response.data
        assert 'removed account' not in response.data['email'][0]

    def test_update_teacher_keeps_own_email(self, authenticated_management_client, teacher_user):
        response = authenticated_management_client.put(
            reverse('management_update_teacher', kwargs={'pk': teacher_user.id}),
            {'email': teacher_user.email, 'first_name': 'Same'}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# MAP-229: one instrument list — every `instruments` payload key is built from
# the teacher's TeacherInstrument rows; the Edit Info endpoint cannot write it.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDerivedInstruments:

    @pytest.fixture
    def rows(self, teacher_user):
        from teacher_profiles.models import TeacherInstrument, TeacherProfile
        profile = TeacherProfile.objects.create(teacher=teacher_user, school=teacher_user.school)
        TeacherInstrument.objects.create(profile=profile, instrument='Violin', skill_ceiling='advanced')
        TeacherInstrument.objects.create(profile=profile, instrument='Cello', skill_ceiling=None)
        return profile

    @staticmethod
    def _payload_instruments(client, teacher, student):
        """The `instruments` value at every management read site, keyed by site."""
        student.assigned_teachers.add(teacher)
        listed = client.get(reverse('management_teacher_list')).data
        detail = client.get(reverse('management_teacher_detail', kwargs={'pk': teacher.id})).data
        students = client.get(reverse('teacher_students', kwargs={'teacher_id': teacher.id})).data
        student_detail = client.get(reverse('management_student_detail', kwargs={'pk': student.id})).data
        users = client.get(reverse('management_all_users'), {'user_type': 'teacher'}).data
        return {
            'teacher_list': next(t['instruments'] for t in listed if t['id'] == teacher.id),
            'teacher_detail': detail['instruments'],
            'teacher_students': students['teacher']['instruments'],
            'assigned_teachers_data': next(
                t['instruments'] for t in student_detail['assigned_teachers_data'] if t['id'] == teacher.id
            ),
            'all_users': next(u['instruments'] for u in users if u['id'] == teacher.id),
        }

    def test_every_read_site_joins_rows_in_name_order(
        self, authenticated_management_client, teacher_user, student_user, rows
    ):
        sites = self._payload_instruments(authenticated_management_client, teacher_user, student_user)

        assert sites == {site: 'Cello, Violin' for site in sites}

    def test_every_read_site_is_empty_without_profile(
        self, authenticated_management_client, teacher_user, student_user
    ):
        sites = self._payload_instruments(authenticated_management_client, teacher_user, student_user)

        assert sites == {site: '' for site in sites}

    def test_adding_a_row_through_the_instruments_api_updates_the_teacher_list(
        self, authenticated_management_client, teacher_user, rows
    ):
        response = authenticated_management_client.post(
            reverse('teacher_instrument_list', kwargs={'teacher_id': teacher_user.id}),
            {'instrument': 'Banjo', 'skill_ceiling': 'beginner'},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED

        listed = authenticated_management_client.get(reverse('management_teacher_list')).data
        assert next(t['instruments'] for t in listed if t['id'] == teacher_user.id) == 'Banjo, Cello, Violin'

    def test_edit_info_ignores_instruments_key(
        self, authenticated_management_client, teacher_user, rows
    ):
        response = authenticated_management_client.put(
            reverse('management_update_teacher', kwargs={'pk': teacher_user.id}),
            {'instruments': 'Kazoo', 'first_name': 'Renamed'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['instruments'] == 'Cello, Violin'
        assert sorted(rows.instruments.values_list('instrument', flat=True)) == ['Cello', 'Violin']
        teacher_user.refresh_from_db()
        assert teacher_user.first_name == 'Renamed'


# ---------------------------------------------------------------------------
# MAP-259: teacher structured address (street_address, city, province,
# postal_code) — written by the management teacher PUT, returned by the
# teacher reads; the student PUT does not gain the fields.
# ---------------------------------------------------------------------------

ADDRESS_FIELDS = ('street_address', 'city', 'province', 'postal_code')


def _address(user):
    user.refresh_from_db()
    return {name: getattr(user, name) for name in ADDRESS_FIELDS}


@pytest.mark.django_db
class TestTeacherStructuredAddress:

    @staticmethod
    def _put(client, route, user, payload):
        return client.put(reverse(route, kwargs={'pk': user.id}), payload, format='json')

    def test_put_teacher_address_is_stored_and_returned_by_every_teacher_read(
        self, authenticated_management_client, teacher_user
    ):
        payload = {
            'street_address': '1055 Canada Pl',
            'city': 'Vancouver',
            'province': 'BC',
            'postal_code': 'v6c0c3',
        }
        stored = payload | {'postal_code': 'V6C 0C3'}

        response = self._put(authenticated_management_client, 'management_update_teacher', teacher_user, payload)

        assert response.status_code == status.HTTP_200_OK, response.data
        assert {k: response.data[k] for k in ADDRESS_FIELDS} == stored
        assert _address(teacher_user) == stored
        assert {k: getattr(teacher_user.history.latest(), k) for k in ADDRESS_FIELDS} == stored

        detail = authenticated_management_client.get(
            reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        )
        assert detail.status_code == status.HTTP_200_OK
        assert {k: detail.data[k] for k in ADDRESS_FIELDS} == stored

        listed = authenticated_management_client.get(reverse('management_teacher_list'))
        row = next(t for t in listed.data if t['id'] == teacher_user.id)
        assert {k: row[k] for k in ADDRESS_FIELDS} == stored

    @pytest.mark.parametrize('field,value', [
        ('province', 'ZZ'),
        ('province', 'Ontario'),
        ('postal_code', '12345'),
        ('postal_code', 'M5H 2N'),
        ('postal_code', 'MM5 H2N'),
    ])
    def test_invalid_province_or_postal_code_is_a_field_error(
        self, authenticated_management_client, teacher_user, field, value
    ):
        before = _address(teacher_user)
        payload = {'street_address': '1 Yonge St', 'city': 'Toronto', 'province': 'ON', 'postal_code': 'M5E 1W7'}

        response = self._put(
            authenticated_management_client, 'management_update_teacher', teacher_user, payload | {field: value}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert set(response.data) == {field}
        assert _address(teacher_user) == before

    def test_blank_values_clear_the_address(self, authenticated_management_client, teacher_user):
        User.objects.filter(pk=teacher_user.pk).update(
            street_address='1 Yonge St', city='Toronto', province='ON', postal_code='M5E 1W7'
        )

        response = self._put(
            authenticated_management_client, 'management_update_teacher', teacher_user,
            {name: '' for name in ADDRESS_FIELDS},
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _address(teacher_user) == {name: '' for name in ADDRESS_FIELDS}

    def test_put_without_address_leaves_it_unchanged(self, authenticated_management_client, teacher_user):
        User.objects.filter(pk=teacher_user.pk).update(
            street_address='1 Yonge St', city='Toronto', province='ON', postal_code='M5E 1W7'
        )
        before = _address(teacher_user)

        response = self._put(
            authenticated_management_client, 'management_update_teacher', teacher_user, {'bio': 'New bio'}
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _address(teacher_user) == before
        assert teacher_user.bio == 'New bio'

    def test_student_put_does_not_write_or_return_the_address(
        self, authenticated_management_client, student_user
    ):
        response = self._put(
            authenticated_management_client, 'management_student_detail', student_user,
            {'street_address': '1 Yonge St', 'city': 'Toronto', 'province': 'ON',
             'postal_code': 'M5E 1W7', 'phone_number': '4165550199'},
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert _address(student_user) == {name: '' for name in ADDRESS_FIELDS}
        assert student_user.phone_number == '4165550199'
        assert not set(ADDRESS_FIELDS) & set(response.data)


# ---------------------------------------------------------------------------
# MAP-251 (Z0 D9): the teacher PUT returns the same record as the teacher
# detail read, plus schedules_updated; input validation is unchanged.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTeacherUpdateResponseShape:

    @staticmethod
    def _detail(client, teacher):
        response = client.get(reverse('management_teacher_detail', kwargs={'pk': teacher.id}))
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_put_response_is_teacher_detail_shape_plus_schedules_updated(
        self, authenticated_management_client, teacher_user
    ):
        response = authenticated_management_client.put(
            reverse('management_update_teacher', kwargs={'pk': teacher_user.id}),
            {'bio': 'Updated bio', 'city': 'Toronto'}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        body = response.json()
        detail = self._detail(authenticated_management_client, teacher_user)
        assert set(body) == set(detail) | {'schedules_updated'}
        assert {k: v for k, v in body.items() if k != 'schedules_updated'} == detail
        assert body['bio'] == 'Updated bio'
        assert body['city'] == 'Toronto'

    def test_put_invalid_input_returns_field_errors_and_writes_nothing(
        self, authenticated_management_client, teacher_user
    ):
        before = self._detail(authenticated_management_client, teacher_user)

        response = authenticated_management_client.put(
            reverse('management_update_teacher', kwargs={'pk': teacher_user.id}),
            {'email': 'not-an-email', 'bio': 'Should not be saved'}, format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert set(response.data) == {'email'}
        assert self._detail(authenticated_management_client, teacher_user) == before


@pytest.mark.django_db
class TestApprovedEmailCreateResponse:
    """MAP-255: the approved-email create response never carries the raw
    invitation token — the invitation email is its only delivery channel."""

    EXPECTED_KEYS = {
        'id', 'email', 'user_type', 'user_type_display', 'approved_by',
        'approved_by_name', 'approved_at', 'notes',
        'invitation_sent', 'invitation_message',
    }

    def _create(self, client, email):
        return client.post(
            reverse('approved_email_list'),
            {'email': email, 'user_type': 'teacher', 'notes': ''},
            format='json',
        )

    def test_create_omits_invitation_token_and_emails_the_link(
        self, authenticated_management_client
    ):
        from django.conf import settings
        from django.core import mail
        from billing.models import InvitationToken

        email = 'invitee@example.com'
        response = self._create(authenticated_management_client, email)

        assert response.status_code == status.HTTP_201_CREATED
        assert set(response.data) == self.EXPECTED_KEYS
        assert response.data['invitation_sent'] is True

        invitation = InvitationToken.objects.get(email=email)
        assert invitation.token not in response.content.decode()

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [email]
        assert f'{settings.FRONTEND_URL}/invite/{invitation.token}' in mail.outbox[0].body

    def test_email_failure_still_omits_invitation_token(
        self, authenticated_management_client
    ):
        import smtplib
        from unittest.mock import patch
        from billing.models import InvitationToken

        email = 'unreachable@example.com'
        with patch(
            'billing.invitation_utils.send_mail',
            side_effect=smtplib.SMTPException('relay down'),
        ):
            response = self._create(authenticated_management_client, email)

        assert response.status_code == status.HTTP_201_CREATED
        assert set(response.data) == self.EXPECTED_KEYS
        assert response.data['invitation_sent'] is False

        invitation = InvitationToken.objects.get(email=email)
        assert invitation.token not in response.content.decode()


# ---------------------------------------------------------------------------
# MAP-176: management bulk status change — PUT management/batches/<id>/lessons/bulk/
# ---------------------------------------------------------------------------

from billing.models import SchoolSettings
from billing.services.bulk_lesson_items import BULK_LESSON_ITEMS_MAX
from billing.views.management import BULK_ALLOWED_STATUSES

BULK_STATE_FIELDS = ('id', 'status', 'teacher_notes', 'cancellation_reason', 'admin_notes')


def _bulk_state(ids):
    return list(BatchLessonItem.objects.filter(id__in=ids).order_by('id').values(*BULK_STATE_FIELDS))


@pytest.mark.django_db
class TestManagementBulkLessonStatus:

    def _put(self, client, batch, body):
        return client.put(
            reverse('management_batch_lesson_items_bulk', kwargs={'batch_id': batch.id}), body, format='json'
        )

    @pytest.fixture
    def batch(self, teacher_user, school):
        return _submitted_batch(teacher_user, school)

    @pytest.fixture
    def items(self, batch, student_user, school_settings):
        return [_ledger_item(batch, student_user, school_settings, day=day) for day in (4, 11, 18)]

    def test_mgmt_bulk_status_update_applies_to_all_selected_items(
        self, authenticated_management_client, batch, items
    ):
        ids = [item.id for item in items]
        response = self._put(authenticated_management_client, batch, {
            'item_ids': ids, 'status': 'cancelled',
            'cancellation_reason': 'Data entry error', 'teacher_notes': 'Wrong teacher',
            'admin_notes': 'Removed per teacher call',
        })

        assert response.status_code == status.HTTP_200_OK
        assert [row['id'] for row in response.data['updated']] == ids
        for row in _bulk_state(ids):
            assert row['status'] == 'cancelled'
            assert row['cancellation_reason'] == 'Data entry error'
            assert row['teacher_notes'] == 'Wrong teacher'
            assert row['admin_notes'] == 'Removed per teacher call'

    @pytest.mark.parametrize('new_status', BULK_ALLOWED_STATUSES)
    def test_mgmt_bulk_accepts_every_status_the_single_route_allows(
        self, authenticated_management_client, batch, items, new_status
    ):
        ids = [item.id for item in items]

        response = self._put(authenticated_management_client, batch, {'item_ids': ids, 'status': new_status})

        assert response.status_code == status.HTTP_200_OK
        assert {row['status'] for row in _bulk_state(ids)} == {new_status}

    @pytest.mark.parametrize('batch_status', ['draft', 'approved'])
    def test_mgmt_bulk_status_update_rejects_non_submitted_batch(
        self, authenticated_management_client, batch, items, batch_status
    ):
        batch.status = batch_status
        batch.save()
        ids = [item.id for item in items]
        before = _bulk_state(ids)

        response = self._put(authenticated_management_client, batch, {'item_ids': ids, 'status': 'cancelled'})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert _bulk_state(ids) == before

    @pytest.mark.django_db(transaction=True)
    def test_mgmt_bulk_status_update_disallowed_status_changes_nothing(
        self, authenticated_management_client, batch, items
    ):
        from billing.models import Lesson
        disallowed = next(code for code, _ in Lesson.LESSON_STATUS if code not in BULK_ALLOWED_STATUSES)
        ids = [item.id for item in items]
        before = _bulk_state(ids)

        response = self._put(authenticated_management_client, batch, {
            'item_ids': ids, 'status': disallowed, 'admin_notes': 'should not land',
        })

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert set(response.data['errors']) == {str(i) for i in ids}
        assert all('status' in err for err in response.data['errors'].values())
        assert _bulk_state(ids) == before

    @pytest.mark.django_db(transaction=True)
    def test_mgmt_bulk_status_update_foreign_or_unknown_item_404_changes_nothing(
        self, authenticated_management_client, batch, items, teacher_user, school,
        student_user, school_settings
    ):
        other_batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=7, year=2026, status='submitted',
        )
        foreign = _ledger_item(other_batch, student_user, school_settings, day=9)
        ids = [item.id for item in items]
        missing = BatchLessonItem.objects.order_by('-id').first().id + 1000
        before = _bulk_state(ids + [foreign.id])

        for stray in (foreign.id, missing):
            response = self._put(authenticated_management_client, batch, {
                'item_ids': ids + [stray], 'status': 'cancelled',
            })
            assert response.status_code == status.HTTP_404_NOT_FOUND

        assert _bulk_state(ids + [foreign.id]) == before

    def test_mgmt_bulk_other_school_batch_is_404(
        self, api_client, batch, items, second_school
    ):
        outsider = User.objects.create_user(
            email='outside.manager@test.com', password='testpass123', user_type='management',
            first_name='Out', last_name='Side', school=second_school, is_approved=True,
        )
        api_client.force_authenticate(user=outsider)
        ids = [item.id for item in items]
        before = _bulk_state(ids)

        response = self._put(api_client, batch, {'item_ids': ids, 'status': 'cancelled'})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert _bulk_state(ids) == before

    def test_mgmt_bulk_more_than_the_cap_is_rejected(self, authenticated_management_client, batch, items):
        ids = [item.id for item in items]
        filler = range(10**6, 10**6 + BULK_LESSON_ITEMS_MAX + 1 - len(ids))
        before = _bulk_state(ids)

        response = self._put(authenticated_management_client, batch, {
            'item_ids': ids + list(filler), 'status': 'cancelled',
        })

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data
        assert _bulk_state(ids) == before

    def test_mgmt_bulk_waived_is_not_converted(
        self, authenticated_management_client, batch, items, school
    ):
        settings = SchoolSettings.get_settings_for_school(school)
        settings.waive_limit_enabled = True
        settings.waive_limit = 1
        settings.waive_period_type = 'rolling'
        settings.waive_period_months = 4
        settings.save()
        ids = [item.id for item in items]
        assert len(ids) > settings.waive_limit

        response = self._put(authenticated_management_client, batch, {'item_ids': ids, 'status': 'waived'})

        assert response.status_code == status.HTTP_200_OK
        assert {row['status'] for row in _bulk_state(ids)} == {'waived'}

    def test_teacher_cannot_call_management_bulk_route(
        self, authenticated_teacher_client, batch, items
    ):
        ids = [item.id for item in items]
        before = _bulk_state(ids)

        response = self._put(authenticated_teacher_client, batch, {'item_ids': ids, 'status': 'cancelled'})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert _bulk_state(ids) == before


# ---------------------------------------------------------------------------
# MAP-293 Section D — contact fields are stored canonical on save
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestContactFieldNormalization:
    """Phones are stored as 10 digits, names Title Case, a city without the
    province it repeats, postal codes A1A 1A1 and emails lowercase."""

    def _create_body(self, **student):
        return {
            'email': 'Thomas.Feinberg@Example.com ',
            'first_name': ' thomas ', 'last_name': 'feinberg',
            'phone_number': '416 822 8104',
            'billing_contact': {
                'contact_type': 'parent', 'first_name': 'mary-jane', 'last_name': "o'neil",
                'email': 'MJ@Example.com', 'phone': '+1 (416) 822-8105',
                'street_address': ' 12 King St ', 'city': 'London, Ontario', 'province': 'ON',
                'postal_code': 'n6a1b2',
            },
        } | student

    def test_create_student_stores_canonical_fields(self, authenticated_management_client):
        response = authenticated_management_client.post(
            '/api/billing/management/students/', self._create_body(), format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        student = User.objects.get(pk=response.data['id'])
        assert (student.first_name, student.last_name) == ('Thomas', 'Feinberg')
        assert student.phone_number == '4168228104'
        assert student.email == 'thomas.feinberg@example.com'
        contact = _Contact.objects.get(student=student)
        assert (contact.first_name, contact.last_name) == ('Mary-Jane', "O'Neil")
        assert contact.phone == '4168228105'
        assert contact.email == 'mj@example.com'
        assert (contact.street_address, contact.city, contact.province) == ('12 King St', 'London', 'ON')
        assert contact.postal_code == 'N6A 1B2'

    def test_create_student_rejects_a_phone_that_is_not_ten_digits(self, authenticated_management_client):
        response = authenticated_management_client.post(
            '/api/billing/management/students/', self._create_body(phone_number='822 8104'), format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['phone_number'] == ['Enter a 10-digit phone number']
        assert not User.objects.filter(email='thomas.feinberg@example.com').exists()

    def test_create_student_lowercases_before_the_uniqueness_check(
        self, authenticated_management_client, student_user
    ):
        response = authenticated_management_client.post(
            '/api/billing/management/students/',
            self._create_body(email=student_user.email.upper()), format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'email' in response.data
        assert User.objects.filter(email__iexact=student_user.email).count() == 1

    def test_contact_update_strips_city_against_the_stored_province(
        self, authenticated_management_client, contact
    ):
        response = authenticated_management_client.put(
            reverse('manage_billable_contact', kwargs={'pk': contact.id}),
            # is_primary sent: a partial PUT without it is refused today (MAP-328).
            {'city': 'Toronto, ON', 'phone': '(647) 555-0199', 'is_primary': True}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        contact.refresh_from_db()
        assert (contact.city, contact.phone) == ('Toronto', '6475550199')

    def test_contact_city_keeps_a_suffix_that_is_not_the_set_province(
        self, authenticated_management_client, contact
    ):
        response = authenticated_management_client.put(
            reverse('manage_billable_contact', kwargs={'pk': contact.id}),
            {'city': 'London, Ontario', 'province': 'BC', 'is_primary': True}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        contact.refresh_from_db()
        assert contact.city == 'London, Ontario'

    def test_teacher_update_normalizes_and_allows_a_blank_phone(
        self, authenticated_management_client, teacher_user
    ):
        url = reverse('management_update_teacher', kwargs={'pk': teacher_user.id})
        response = authenticated_management_client.put(url, {
            'first_name': 'lila', 'last_name': 'McDonald', 'phone_number': '1-416-822-8104',
            'city': 'ottawa, ontario', 'province': 'ON', 'postal_code': 'k1a 0b1',
        }, format='json')

        assert response.status_code == status.HTTP_200_OK, response.data
        teacher_user.refresh_from_db()
        assert (teacher_user.first_name, teacher_user.last_name) == ('Lila', 'McDonald')
        assert teacher_user.phone_number == '4168228104'
        assert (teacher_user.city, teacher_user.postal_code) == ('ottawa', 'K1A 0B1')

        blank = authenticated_management_client.put(url, {'phone_number': ''}, format='json')
        assert blank.status_code == status.HTTP_200_OK, blank.data
        teacher_user.refresh_from_db()
        assert teacher_user.phone_number == ''

    def test_school_update_normalizes_phone_postal_city_and_email(
        self, authenticated_management_client, school
    ):
        response = authenticated_management_client.patch(
            '/api/billing/management/school/update/',
            {'phone_number': '416.822.8104', 'postal_code': 'm5h2n2', 'city': 'Toronto, Ontario',
             'province': 'ON', 'email': 'Office@School.CA'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        school.refresh_from_db()
        assert (school.phone_number, school.postal_code, school.city, school.email) == (
            '4168228104', 'M5H 2N2', 'Toronto', 'office@school.ca'
        )

    def test_school_update_rejects_a_bad_phone(self, authenticated_management_client, school):
        before = school.phone_number
        response = authenticated_management_client.patch(
            '/api/billing/management/school/update/', {'phone_number': '555-0100'}, format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['phone_number'] == ['Enter a 10-digit phone number']
        school.refresh_from_db()
        assert school.phone_number == before


# ---------------------------------------------------------------------------
# MAP-302: student enrolment status. `status` is a new field next to the
# soft-delete flag `is_active`; only active students are billed and counted.
# ---------------------------------------------------------------------------

from django.db import connection
from django.test.utils import CaptureQueriesContext

NON_ACTIVE_STATUSES = [value for value, _ in User.STUDENT_STATUSES if value != 'active']


def _student(school, email, teacher=None, status_value='active', contact=True):
    student = User.objects.create_user(
        email=email, password='x', user_type='student', first_name='Status',
        last_name=email.split('@')[0], school=school, is_approved=True,
    )
    if status_value != 'active':
        student.status = status_value
        student.save(update_fields=['status'])
    if teacher is not None:
        student.assigned_teachers.add(teacher)
    if contact:
        _Contact.objects.create(
            student=student, school=school, is_primary=True, first_name='Pat',
            last_name='Parent', email=f'parent.{email}', phone='4165550100',
            street_address='1 Main St', city='Toronto', province='ON', postal_code='M5H 2N2',
        )
    return student


@pytest.mark.django_db
class TestStudentStatus:

    def _detail(self, student):
        return reverse('management_student_detail', kwargs={'pk': student.id})

    def test_new_student_defaults_to_active(self, school):
        assert _student(school, 'fresh@test.com').status == 'active'

    @pytest.mark.parametrize('new_status', NON_ACTIVE_STATUSES)
    def test_put_status_persists(self, authenticated_management_client, school, new_status):
        student = _student(school, 'put@test.com')

        response = authenticated_management_client.put(
            self._detail(student), {'status': new_status}, format='json'
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data['status'] == new_status
        student.refresh_from_db()
        assert student.status == new_status
        assert student.is_active is True  # soft delete untouched

    def test_put_invalid_status_400(self, authenticated_management_client, school):
        student = _student(school, 'bad@test.com')

        response = authenticated_management_client.put(
            self._detail(student), {'status': 'enrolled'}, format='json'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'status' in response.data
        student.refresh_from_db()
        assert student.status == 'active'

    def test_teacher_cannot_set_status(self, authenticated_teacher_client, school, teacher_user):
        student = _student(school, 'teach@test.com', teacher=teacher_user)

        response = authenticated_teacher_client.put(
            self._detail(student), {'status': 'waitlist'}, format='json'
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        student.refresh_from_db()
        assert student.status == 'active'

    def test_teacher_update_ignores_status(self, authenticated_management_client, teacher_user):
        response = authenticated_management_client.put(
            reverse('management_update_teacher', kwargs={'pk': teacher_user.id}),
            {'status': 'waitlist'}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        teacher_user.refresh_from_db()
        assert teacher_user.status == 'active'

    def test_list_emits_status_schedules_primary_address(
        self, authenticated_management_client, school, teacher_user
    ):
        student = _student(school, 'payload@test.com', teacher=teacher_user, status_value='waitlist')
        active = _Schedule.objects.create(
            teacher=teacher_user, student=student, school=school, day_of_week=0,
            start_time=time(17, 0), duration=Decimal('1.00'), teacher_rate=Decimal('45.00'),
            student_rate=Decimal('60.00'), start_date=date(2026, 9, 7),
        )
        _Schedule.objects.create(
            teacher=teacher_user, student=student, school=school, day_of_week=2,
            start_time=time(16, 0), duration=Decimal('0.50'), teacher_rate=Decimal('45.00'),
            student_rate=Decimal('60.00'), start_date=date(2026, 9, 7), is_active=False,
        )
        bare = _student(school, 'bare@test.com', contact=False)

        response = authenticated_management_client.get(reverse('management_students'))

        assert response.status_code == status.HTTP_200_OK
        rows = {row['id']: row for row in response.data}
        # The list endpoint does not filter by status.
        assert rows[student.id]['status'] == 'waitlist'
        assert rows[student.id]['schedules'] == [{
            'id': active.id, 'teacher': teacher_user.id,
            'teacher_name': teacher_user.get_full_name(), 'day_of_week': 0,
            'start_time': '17:00:00', 'duration': '1.00',
        }]
        assert rows[student.id]['primary_contact_address'] == {
            'street_address': '1 Main St', 'city': 'Toronto', 'province': 'ON',
            'postal_code': 'M5H 2N2',
        }
        assert rows[bare.id]['schedules'] == []
        assert rows[bare.id]['primary_contact_address'] is None

    def test_non_students_emit_constant_shape(self, teacher_user):
        from billing.serializers import UserSerializer
        data = UserSerializer(teacher_user).data
        assert (data['status'], data['schedules'], data['primary_contact_address']) == ('active', [], None)

    def test_list_query_count_constant(self, authenticated_management_client, school, teacher_user):
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                response = authenticated_management_client.get(reverse('management_students'))
            assert response.status_code == status.HTTP_200_OK
            return len(ctx.captured_queries), len(response.data)

        def add(n, offset):
            for i in range(n):
                s = _student(school, f'n{offset + i}@test.com', teacher=teacher_user)
                _Schedule.objects.create(
                    teacher=teacher_user, student=s, school=school, day_of_week=i % 7,
                    start_time=time(15, 0), duration=Decimal('1.00'),
                    teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'),
                    start_date=date(2026, 9, 7),
                )

        add(1, 0)
        one_queries, one_rows = count_queries()
        add(4, 1)
        five_queries, five_rows = count_queries()

        assert (one_rows, five_rows) == (1, 5)
        assert five_queries == one_queries

    def test_total_students_counts_active_only(
        self, authenticated_management_client, school, teacher_user
    ):
        active = _student(school, 'tally-active@test.com', teacher=teacher_user)
        for value in NON_ACTIVE_STATUSES:
            _student(school, f'tally-{value}@test.com', teacher=teacher_user, status_value=value)

        rows = authenticated_management_client.get(reverse('management_teacher_list')).data
        row = next(r for r in rows if r['id'] == teacher_user.id)
        detail = authenticated_management_client.get(
            reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        ).data
        page = authenticated_management_client.get(
            reverse('teacher_students', kwargs={'teacher_id': teacher_user.id})
        ).data

        assert row['total_students'] == detail['total_students'] == page['total_students'] == 1
        # The teacher's students page still lists every non-removed student (Q1 b).
        assert {s['id'] for s in page['students']} >= {active.id}
        assert len(page['students']) == 1 + len(NON_ACTIVE_STATUSES)

    def test_school_student_count_active_only(self, authenticated_management_client, school):
        before = authenticated_management_client.get(reverse('get_current_school')).data['student_count']
        _student(school, 'count-active@test.com')
        for value in NON_ACTIVE_STATUSES:
            _student(school, f'count-{value}@test.com', status_value=value)

        after = authenticated_management_client.get(reverse('get_current_school')).data['student_count']

        assert after == before + 1
