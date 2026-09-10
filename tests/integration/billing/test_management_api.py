"""
Integration tests for management API endpoints.

Tests cover:
- Global rate settings CRUD operations
- Teacher management and rate updates
- Permission enforcement (management-only)
- Rate locking mechanism (existing lessons unchanged)
"""

import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from billing.models import GlobalRateSettings, Lesson, Invoice, MonthlyInvoiceBatch
from django.contrib.auth import get_user_model
from faker import Faker

User = get_user_model()


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
                return fake.numerify('###########')
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
        for name in ('email', 'first_name', 'last_name', 'phone_number', 'address', 'bio', 'instruments'):
            assert getattr(user, name) == payload[name], name
        assert user.hourly_rate == Decimal(payload['hourly_rate'])
        assert set(user.assigned_teachers.values_list('id', flat=True)) == {teacher_user.id}


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

        assert second.status_code == 400  # invoice already generated for this batch
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
