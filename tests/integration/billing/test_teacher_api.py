"""
Integration tests for teacher-specific API endpoints.

Tests cover:
- Teacher assigned students endpoint
- Permission enforcement (teacher-only)
- Student assignment filtering
- School isolation
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from django.urls import NoReverseMatch
from decimal import Decimal

from datetime import date, time
from django.db import connection
from django.test.utils import CaptureQueriesContext

from billing.models import (
    BatchLessonItem, BillableContact, Invoice, Lesson, MonthlyInvoiceBatch,
    RecurringLessonsSchedule,
)
from faker import Faker

User = get_user_model()


@pytest.fixture
def api_client():
    """Create an API client for testing."""
    return APIClient()


@pytest.fixture
def authenticated_teacher_client(api_client, teacher_user):
    """Create an authenticated API client with teacher user."""
    api_client.force_authenticate(user=teacher_user)
    return api_client


@pytest.fixture
def authenticated_management_client(api_client, management_user):
    """Create an authenticated API client with management user."""
    api_client.force_authenticate(user=management_user)
    return api_client


@pytest.mark.django_db
class TestTeacherAssignedStudentsAPI:
    """Tests for /api/billing/teacher/students/ endpoint."""

    def test_teacher_can_get_assigned_students(
        self, authenticated_teacher_client, teacher_user, school
    ):
        """Teachers can retrieve their assigned students."""
        # Create students assigned to this teacher
        student1 = User.objects.create(
            email='student1@test.com',
            first_name='Alice',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )
        student2 = User.objects.create(
            email='student2@test.com',
            first_name='Bob',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )

        # Assign students to teacher
        teacher_user.assigned_students.add(student1, student2)

        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

        # Verify both students are returned
        student_emails = [s['email'] for s in response.data]
        assert 'student1@test.com' in student_emails
        assert 'student2@test.com' in student_emails

    def test_teacher_only_sees_their_assigned_students(
        self, authenticated_teacher_client, teacher_user, school
    ):
        """Teachers only see students assigned to them, not other students."""
        # Create student assigned to this teacher
        assigned_student = User.objects.create(
            email='assigned@test.com',
            first_name='Assigned',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )
        teacher_user.assigned_students.add(assigned_student)

        # Create another teacher and their student
        other_teacher = User.objects.create(
            email='other_teacher@test.com',
            first_name='Other',
            last_name='Teacher',
            user_type='teacher',
            is_approved=True,
            school=school
        )
        other_student = User.objects.create(
            email='other@test.com',
            first_name='Other',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )
        other_teacher.assigned_students.add(other_student)

        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['email'] == 'assigned@test.com'

    def test_teacher_does_not_see_inactive_students(
        self, authenticated_teacher_client, teacher_user, school
    ):
        """Inactive students are filtered out from teacher's assigned students."""
        # Create active student
        active_student = User.objects.create(
            email='active@test.com',
            first_name='Active',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )

        # Create inactive student
        inactive_student = User.objects.create(
            email='inactive@test.com',
            first_name='Inactive',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=False,  # Inactive
            school=school
        )

        # Assign both to teacher
        teacher_user.assigned_students.add(active_student, inactive_student)

        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['email'] == 'active@test.com'

    def test_management_cannot_access_teacher_endpoint(
        self, authenticated_management_client
    ):
        """Management users cannot access teacher-specific endpoint."""
        url = reverse('teacher_assigned_students')
        response = authenticated_management_client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert 'error' in response.data

    def test_unauthenticated_user_cannot_access(self, api_client):
        """Unauthenticated users cannot access teacher endpoint."""
        url = reverse('teacher_assigned_students')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_teacher_with_no_assigned_students_gets_empty_list(
        self, authenticated_teacher_client, teacher_user
    ):
        """Teachers with no assigned students receive an empty list."""
        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0
        assert response.data == []

    def test_response_includes_student_details(
        self, authenticated_teacher_client, teacher_user, school
    ):
        """Response includes all necessary student details."""
        student = User.objects.create(
            email='student@test.com',
            first_name='Test',
            last_name='Student',
            user_type='student',
            is_approved=True,
            is_active=True,
            school=school
        )
        teacher_user.assigned_students.add(student)

        url = reverse('teacher_assigned_students')
        response = authenticated_teacher_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

        student_data = response.data[0]
        assert student_data['email'] == 'student@test.com'
        assert student_data['first_name'] == 'Test'
        assert student_data['last_name'] == 'Student'
        assert student_data['user_type'] == 'student'
        assert 'id' in student_data

    def test_assigned_students_query_count_constant(
        self, authenticated_teacher_client, teacher_user, school
    ):
        """The list costs the same number of queries for 1 student as for 5 (MAP-364)."""
        url = reverse('teacher_assigned_students')

        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                response = authenticated_teacher_client.get(url)
            assert response.status_code == status.HTTP_200_OK
            return len(ctx.captured_queries), len(response.data)

        def add(n, offset):
            for i in range(n):
                student = User.objects.create(
                    email=f'q{offset + i}@test.com', first_name='Query',
                    last_name=f'Student{offset + i}', user_type='student',
                    is_approved=True, is_active=True, school=school,
                )
                teacher_user.assigned_students.add(student)
                BillableContact.objects.create(
                    student=student, school=school, is_primary=True, first_name='Pat',
                    last_name='Parent', email=f'parent.q{offset + i}@test.com',
                    phone='4165550100', street_address='1 Main St', city='Toronto',
                    province='ON', postal_code='M5H 2N2',
                )
                RecurringLessonsSchedule.objects.create(
                    teacher=teacher_user, student=student, school=school,
                    day_of_week=i % 7, start_time=time(15, 0), duration=Decimal('1.00'),
                    teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'),
                    start_date=date(2026, 9, 7),
                )

        add(1, 0)
        one_queries, one_rows = count_queries()
        add(4, 1)
        five_queries, five_rows = count_queries()

        assert (one_rows, five_rows) == (1, 5)
        assert five_queries == one_queries



@pytest.mark.django_db
class TestManagementTeacherRoutesAuthentication:
    """
    SEC-03 (MAP-178): the management teacher routes are the only teacher
    directory. Unauthenticated -> 401; non-management roles -> 403.
    """

    def test_unauthenticated_teacher_list_returns_401(self, api_client):
        """Unauthenticated GET to management/teachers/ must return 401, not teacher PII."""
        url = reverse('management_teacher_list')
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unauthenticated_teacher_detail_returns_401(self, api_client, teacher_user):
        """Unauthenticated GET to management/teachers/<pk>/ must return 401."""
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize('role_fixture', ['teacher_user', 'student_user'])
    def test_non_management_teacher_list_returns_403(self, request, api_client, role_fixture):
        """A teacher or student session gets 403 from the management teacher list."""
        api_client.force_authenticate(user=request.getfixturevalue(role_fixture))
        response = api_client.get(reverse('management_teacher_list'))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert 'error' in response.data

    @pytest.mark.parametrize('role_fixture', ['teacher_user', 'student_user'])
    def test_non_management_teacher_detail_returns_403(
        self, request, api_client, teacher_user, role_fixture
    ):
        """A teacher or student session gets 403 from the management teacher detail."""
        api_client.force_authenticate(user=request.getfixturevalue(role_fixture))
        url = reverse('management_teacher_detail', kwargs={'pk': teacher_user.id})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert 'error' in response.data


# MAP-178: the seven legacy generic routes no longer exist.
LEGACY_ROUTE_NAMES = [
    'teacher_list', 'student_list', 'lesson_list',
    'teacher_detail', 'student_detail', 'lesson_detail', 'invoice_detail',
]

# MAP-203: the seven @planned routes with no frontend caller no longer exist.
# (name, kwargs) — the kwargs are the real ones so that a still-registered
# route would reverse successfully and fail the test.
MAP203_ROUTE_NAMES = [
    ('all_teachers', {}),
    ('approve_teacher', {'teacher_id': 1}),
    ('request_lesson', {}),
    ('confirm_lesson', {'lesson_id': 1}),
    ('complete_lesson', {'lesson_id': 1}),
    ('teacher_invoice_list', {}),
    ('approve_teacher_invoice', {'invoice_id': 1}),
]

LEGACY_ROUTE_PATHS = [
    'teachers', 'students', 'lessons',
    'teacher_pk', 'student_pk', 'lesson_pk', 'invoice_pk',
    # MAP-203
    'teachers_all', 'teacher_approve', 'lesson_request', 'lesson_confirm',
    'lesson_complete', 'teacher_invoices', 'teacher_invoice_approve',
]

ROLE_FIXTURES = ['anonymous', 'student_user', 'teacher_user', 'management_user']


@pytest.fixture
def legacy_route_paths(school, teacher_user, student_user):
    """
    Concrete legacy paths pointing at rows that DO exist, so a 404 can only
    mean "route does not exist", never "row not found".
    """
    lesson = Lesson.objects.filter(teacher=teacher_user, student=student_user).first()
    invoice = Invoice.objects.create(
        invoice_type='teacher_payment',
        teacher=teacher_user,
        school=school,
        status='pending',
        payment_balance=Decimal('100.00'),
        total_amount=Decimal('100.00'),
    )
    return {
        'teachers': '/api/billing/teachers/',
        'students': '/api/billing/students/',
        'lessons': '/api/billing/lessons/',
        'teacher_pk': f'/api/billing/teachers/{teacher_user.id}/',
        'student_pk': f'/api/billing/students/{student_user.id}/',
        'lesson_pk': f'/api/billing/lessons/{lesson.id}/',
        'invoice_pk': f'/api/billing/invoices/{invoice.id}/',
        # MAP-203
        'teachers_all': '/api/billing/teachers/all/',
        'teacher_approve': f'/api/billing/teachers/{teacher_user.id}/approve/',
        'lesson_request': '/api/billing/lessons/request/',
        'lesson_confirm': f'/api/billing/lessons/{lesson.id}/confirm/',
        'lesson_complete': f'/api/billing/lessons/{lesson.id}/complete/',
        'teacher_invoices': '/api/billing/invoices/teacher/',
        'teacher_invoice_approve': f'/api/billing/invoices/teacher/{invoice.id}/approve/',
    }


@pytest.mark.django_db
class TestLegacyGenericRoutesRemoved:
    """MAP-178 + MAP-203 acceptance: each deleted route -> 404 for every role."""

    @pytest.mark.parametrize('route_name', LEGACY_ROUTE_NAMES)
    def test_legacy_route_name_is_not_registered(self, route_name):
        """The URL name is gone from billing/urls.py."""
        with pytest.raises(NoReverseMatch):
            reverse(route_name, kwargs={'pk': 1} if route_name.endswith('_detail') else None)

    @pytest.mark.parametrize('route_name, kwargs', MAP203_ROUTE_NAMES)
    def test_map203_route_name_is_not_registered(self, route_name, kwargs):
        """MAP-203: the URL name is gone from billing/urls.py."""
        with pytest.raises(NoReverseMatch):
            reverse(route_name, kwargs=kwargs or None)

    @pytest.mark.parametrize('role_fixture', ROLE_FIXTURES)
    @pytest.mark.parametrize('route_key', LEGACY_ROUTE_PATHS)
    def test_legacy_route_returns_404_for_every_role(
        self, request, api_client, legacy_route_paths, route_key, role_fixture
    ):
        if role_fixture != 'anonymous':
            api_client.force_authenticate(user=request.getfixturevalue(role_fixture))
        response = api_client.get(legacy_route_paths[route_key])
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_teacher_put_invoice_detail_status_paid_returns_404(
        self, api_client, teacher_user, legacy_route_paths
    ):
        """
        MAP-178 acceptance: a teacher can no longer mark their own invoice paid
        through invoices/<pk>/. The route is gone (404) and the row is untouched.
        """
        api_client.force_authenticate(user=teacher_user)
        invoice_id = int(legacy_route_paths['invoice_pk'].rstrip('/').rsplit('/', 1)[1])

        response = api_client.put(
            legacy_route_paths['invoice_pk'],
            {'status': 'paid', 'date_paid': '2026-09-01', 'reference_number': 'SELF-PAID'},
            format='json',
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        invoice = Invoice.objects.get(pk=invoice_id)
        assert invoice.status == 'pending'
        assert invoice.date_paid is None
        assert invoice.reference_number is None


@pytest.mark.django_db
class TestSubmitLessonsIgnoresBodyStatus:
    """MAP-178 acceptance: invoice status is server-set; a body status is never read."""

    def test_submit_lessons_with_status_paid_creates_pending_invoice(
        self, api_client, teacher_user, school_settings
    ):
        api_client.force_authenticate(user=teacher_user)

        body = {
            'month': 'September 2026',
            'status': 'paid',
            'date_paid': '2026-09-01',
            'reference_number': 'SELF-PAID',
            'lessons': [
                {
                    'student_name': 'Brand New Student',
                    'scheduled_date': '2026-09-01T14:00:00Z',
                    'duration': 1.0,
                    'lesson_type': 'online',
                }
            ],
            'due_date': '2026-09-30T00:00:00Z',
        }

        response = api_client.post(reverse('submit_lessons_for_invoice'), body, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        invoice = Invoice.objects.get(pk=response.data['invoice']['id'])
        assert invoice.teacher_id == teacher_user.id
        assert invoice.status == 'pending'
        assert invoice.date_paid is None
        assert invoice.reference_number is None
        assert response.data['invoice']['status'] == 'pending'


# ---------------------------------------------------------------------------
# MAP-179: teacher one-off lesson creation — strict seven-field input,
# server-derived rates, assigned same-school students only.
# ---------------------------------------------------------------------------

SEVEN_FIELDS = {'student', 'scheduled_date', 'start_time', 'duration', 'lesson_type', 'status', 'teacher_notes'}


@pytest.fixture
def assigned_student(teacher_user, student_user):
    student_user.assigned_teachers.add(teacher_user)
    return student_user


@pytest.fixture
def draft_batch(teacher_user, school):
    return MonthlyInvoiceBatch.objects.create(teacher=teacher_user, school=school, month=9, year=2026, status='draft')


def _live_payload(student, **overrides):
    """Exactly what src/queries/useBatchLessons.ts::useAddLessonItem sends."""
    return {
        'student': student.id,
        'scheduled_date': '2026-09-03',
        'start_time': '14:00:00',
        'duration': 1.0,
        'lesson_type': 'in_person',
        'status': 'completed',
        'teacher_notes': 'Scales and arpeggios',
    } | overrides


@pytest.mark.django_db
class TestTeacherBatchAddLesson:

    def _post(self, client, batch, payload):
        return client.post(reverse('batch_add_lesson', kwargs={'batch_id': batch.id}), payload, format='json')

    @pytest.mark.parametrize('extra', [
        {'teacher_rate': 9999},
        {'student_rate': -50},
        {'admin_notes': 'x'},
        {'is_one_off': False},
    ])
    def test_unknown_key_is_rejected_and_nothing_written(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings, extra
    ):
        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(assigned_student, **extra))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == {'error': ['unknown_fields'], 'fields': sorted(extra)}
        assert not BatchLessonItem.objects.exists()

    # MAP-271 Q2 / MAP-272: teacher_cancelled and promo are not offered in the one-off add.
    @pytest.mark.parametrize(
        'bad_status',
        ['waived', 'trial', 'requested', 'forfeited', 'teacher_cancelled', 'promo'],
    )
    def test_status_outside_teacher_choices_is_rejected(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings, bad_status
    ):
        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(assigned_student, status=bad_status))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'status' in response.data
        assert not BatchLessonItem.objects.exists()

    def test_student_from_another_school_is_rejected(
        self, authenticated_teacher_client, draft_batch, teacher_user, second_school, school_settings
    ):
        other = User.objects.create_user(
            email='other_school_student@test.com', password='x', user_type='student',
            first_name='O', last_name='S', school=second_school, is_approved=True,
        )
        other.assigned_teachers.add(teacher_user)

        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(other))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'student' in response.data
        assert not BatchLessonItem.objects.exists()

    def test_unassigned_same_school_student_is_rejected(
        self, authenticated_teacher_client, draft_batch, student_user, school_settings
    ):
        assert not student_user.assigned_teachers.exists()

        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(student_user))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'student' in response.data
        assert not BatchLessonItem.objects.exists()

    def test_live_payload_in_person_uses_fixture_rates(
        self, authenticated_teacher_client, draft_batch, assigned_student, teacher_user, school_settings
    ):
        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(assigned_student))

        assert response.status_code == status.HTTP_201_CREATED, response.data
        item = BatchLessonItem.objects.get(pk=response.data['id'])
        assert item.teacher_rate == teacher_user.hourly_rate
        assert item.student_rate == school_settings.inperson_student_rate
        assert item.is_one_off is True
        assert item.status == 'completed'   # student_user already has a completed lesson
        assert item.batch_id == draft_batch.id
        assert item.teacher_notes == 'Scales and arpeggios'

    def test_live_payload_online_uses_school_online_rates(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings
    ):
        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(assigned_student, lesson_type='online'))

        assert response.status_code == status.HTTP_201_CREATED, response.data
        item = BatchLessonItem.objects.get(pk=response.data['id'])
        assert item.teacher_rate == school_settings.online_teacher_rate
        assert item.student_rate == school_settings.online_student_rate

    # MAP-310: the add body accepts completed and confirmed only.
    def test_add_lesson_completed_status_is_created(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings
    ):
        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(assigned_student, status='completed'))

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert BatchLessonItem.objects.get(pk=response.data['id']).status == 'completed'

    def test_add_lesson_confirmed_status_is_created(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings
    ):
        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(assigned_student, status='confirmed'))

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert BatchLessonItem.objects.get(pk=response.data['id']).status == 'confirmed'

    def test_add_lesson_bare_cancelled_status_is_rejected(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings
    ):
        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(assigned_student, status='cancelled'))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert set(response.data) == {'status'}
        assert not BatchLessonItem.objects.exists()

    def test_first_lesson_for_new_student_becomes_trial(
        self, authenticated_teacher_client, draft_batch, teacher_user, school, school_settings
    ):
        newcomer = User.objects.create_user(
            email='newcomer@test.com', password='x', user_type='student',
            first_name='New', last_name='Comer', school=school, is_approved=True,
        )
        newcomer.assigned_teachers.add(teacher_user)

        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(newcomer, status='completed'))

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert BatchLessonItem.objects.get(pk=response.data['id']).status == 'trial'

    def test_duration_omitted_is_rejected_and_nothing_written(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings
    ):
        """P0 audit 2026-09-09: duration has a model default, but the teacher
        payload must state it — before this a missing duration wrote the row
        and then 500'd while rendering the response."""
        payload = _live_payload(assigned_student)
        del payload['duration']

        response = self._post(authenticated_teacher_client, draft_batch, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'duration' in response.data
        assert not BatchLessonItem.objects.exists()

    def test_fuzz_every_model_field_only_the_seven_are_accepted(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings
    ):
        fake = Faker()
        Faker.seed(179)
        all_fields = {f.name for f in BatchLessonItem._meta.get_fields() if f.concrete}
        assert SEVEN_FIELDS < all_fields
        payload = _live_payload(assigned_student)
        for name in all_fields - SEVEN_FIELDS:
            payload[name] = fake.pystr(max_chars=12)

        response = self._post(authenticated_teacher_client, draft_batch, payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == {'error': ['unknown_fields'], 'fields': sorted(all_fields - SEVEN_FIELDS)}
        assert not BatchLessonItem.objects.exists()

        accepted = self._post(authenticated_teacher_client, draft_batch, _live_payload(assigned_student))
        assert accepted.status_code == status.HTTP_201_CREATED
        assert BatchLessonItem.objects.count() == 1


# ---------------------------------------------------------------------------
# MAP-176: teacher bulk status change — PUT teacher/batches/<id>/lessons/bulk/
# ---------------------------------------------------------------------------

from datetime import date as _date, time as _time

from billing.models import SchoolSettings
from billing.services.bulk_lesson_items import BULK_LESSON_ITEMS_MAX

ITEM_STATE_FIELDS = ('id', 'status', 'teacher_notes', 'cancellation_reason', 'admin_notes', 'scheduled_date')


def _bulk_item(batch, student, school_settings, day, status='confirmed', is_one_off=False):
    return BatchLessonItem.objects.create(
        batch=batch, student=student,
        scheduled_date=_date(batch.year, batch.month, day), start_time=_time(15, 0),
        duration=Decimal('1.0'), lesson_type='online',
        teacher_rate=school_settings.online_teacher_rate,
        student_rate=school_settings.online_student_rate,
        status=status, is_one_off=is_one_off,
    )


def _item_state(ids):
    return list(BatchLessonItem.objects.filter(id__in=ids).order_by('id').values(*ITEM_STATE_FIELDS))


@pytest.mark.django_db
class TestTeacherBulkLessonStatus:

    def _put(self, client, batch, body):
        return client.put(
            reverse('batch_lesson_items_bulk', kwargs={'batch_id': batch.id}), body, format='json'
        )

    @pytest.fixture
    def items(self, draft_batch, assigned_student, school_settings):
        return [_bulk_item(draft_batch, assigned_student, school_settings, day) for day in (3, 10, 17)]

    def test_bulk_status_update_applies_to_all_selected_items(
        self, authenticated_teacher_client, draft_batch, items
    ):
        ids = [item.id for item in items]
        response = self._put(authenticated_teacher_client, draft_batch, {
            'item_ids': ids, 'status': 'cancelled',
            'cancellation_reason': 'Entered in error', 'teacher_notes': 'Not my student',
        })

        assert response.status_code == status.HTTP_200_OK
        assert [row['id'] for row in response.data['updated']] == ids
        for row in _item_state(ids):
            assert row['status'] == 'cancelled'
            assert row['cancellation_reason'] == 'Entered in error'
            assert row['teacher_notes'] == 'Not my student'

    def test_updated_follows_request_order(self, authenticated_teacher_client, draft_batch, items):
        ids = [item.id for item in reversed(items)]

        response = self._put(authenticated_teacher_client, draft_batch, {'item_ids': ids, 'status': 'completed'})

        assert response.status_code == status.HTTP_200_OK
        assert [row['id'] for row in response.data['updated']] == ids

    def test_unselected_items_are_untouched(
        self, authenticated_teacher_client, draft_batch, items, assigned_student, school_settings
    ):
        other = _bulk_item(draft_batch, assigned_student, school_settings, 24)
        before = _item_state([other.id])

        response = self._put(authenticated_teacher_client, draft_batch, {
            'item_ids': [item.id for item in items], 'status': 'cancelled',
        })

        assert response.status_code == status.HTTP_200_OK
        assert _item_state([other.id]) == before

    @pytest.mark.parametrize('batch_status', ['submitted', 'approved'])
    def test_bulk_status_update_rejects_non_draft_batch(
        self, authenticated_teacher_client, draft_batch, items, batch_status
    ):
        draft_batch.status = batch_status
        draft_batch.save()
        ids = [item.id for item in items]
        before = _item_state(ids)

        response = self._put(authenticated_teacher_client, draft_batch, {'item_ids': ids, 'status': 'cancelled'})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert _item_state(ids) == before

    @pytest.mark.django_db(transaction=True)
    def test_bulk_status_update_invalid_status_changes_nothing(
        self, authenticated_teacher_client, draft_batch, items
    ):
        ids = [item.id for item in items]
        before = _item_state(ids)

        response = self._put(authenticated_teacher_client, draft_batch, {
            'item_ids': ids, 'status': 'not-a-status', 'teacher_notes': 'should not land',
        })

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert set(response.data['errors']) == {str(i) for i in ids}
        assert all('status' in err for err in response.data['errors'].values())
        assert _item_state(ids) == before

    @pytest.mark.django_db(transaction=True)
    def test_bulk_status_update_foreign_or_unknown_item_404_changes_nothing(
        self, authenticated_teacher_client, draft_batch, items, teacher_user, school,
        assigned_student, school_settings
    ):
        other_batch = MonthlyInvoiceBatch.objects.create(
            teacher=teacher_user, school=school, month=10, year=2026, status='draft'
        )
        foreign = _bulk_item(other_batch, assigned_student, school_settings, 5)
        ids = [item.id for item in items]
        missing = BatchLessonItem.objects.order_by('-id').first().id + 1000
        before = _item_state(ids + [foreign.id])

        for stray in (foreign.id, missing):
            response = self._put(authenticated_teacher_client, draft_batch, {
                'item_ids': ids + [stray], 'status': 'cancelled',
            })
            assert response.status_code == status.HTTP_404_NOT_FOUND

        assert _item_state(ids + [foreign.id]) == before

    def test_other_teachers_batch_is_404(
        self, api_client, draft_batch, items, school
    ):
        other_teacher = User.objects.create_user(
            email='other.teacher@test.com', password='testpass123', user_type='teacher',
            first_name='Other', last_name='Teacher', school=school, is_approved=True,
        )
        api_client.force_authenticate(user=other_teacher)
        ids = [item.id for item in items]
        before = _item_state(ids)

        response = self._put(api_client, draft_batch, {'item_ids': ids, 'status': 'cancelled'})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert _item_state(ids) == before

    def test_more_than_the_cap_is_rejected(self, authenticated_teacher_client, draft_batch, items):
        ids = [item.id for item in items]
        filler = range(10**6, 10**6 + BULK_LESSON_ITEMS_MAX + 1 - len(ids))
        body = {'item_ids': ids + list(filler), 'status': 'cancelled'}
        assert len(body['item_ids']) == BULK_LESSON_ITEMS_MAX + 1
        before = _item_state(ids)

        response = self._put(authenticated_teacher_client, draft_batch, body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data
        assert _item_state(ids) == before

    @pytest.mark.parametrize('body', [
        {'status': 'cancelled'},
        {'item_ids': [], 'status': 'cancelled'},
        {'item_ids': 'all', 'status': 'cancelled'},
        {'item_ids': ['1'], 'status': 'cancelled'},
        {'item_ids': [True], 'status': 'cancelled'},
        {'item_ids': None},
    ])
    def test_malformed_body_is_rejected(self, authenticated_teacher_client, draft_batch, items, body):
        ids = [item.id for item in items]
        before = _item_state(ids)

        response = self._put(authenticated_teacher_client, draft_batch, body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'error' in response.data
        assert _item_state(ids) == before

    def test_missing_status_is_rejected(self, authenticated_teacher_client, draft_batch, items):
        ids = [item.id for item in items]
        before = _item_state(ids)

        response = self._put(authenticated_teacher_client, draft_batch, {'item_ids': ids, 'teacher_notes': 'x'})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert _item_state(ids) == before

    def test_duplicate_ids_are_rejected(self, authenticated_teacher_client, draft_batch, items):
        ids = [item.id for item in items]
        before = _item_state(ids)

        response = self._put(authenticated_teacher_client, draft_batch, {
            'item_ids': ids + [ids[0]], 'status': 'cancelled',
        })

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert _item_state(ids) == before

    def test_date_and_admin_fields_in_body_are_ignored(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings
    ):
        one_off = _bulk_item(draft_batch, assigned_student, school_settings, 8, is_one_off=True)
        before = _item_state([one_off.id])[0]

        response = self._put(authenticated_teacher_client, draft_batch, {
            'item_ids': [one_off.id], 'status': 'cancelled',
            'scheduled_date': '2026-09-28', 'admin_notes': 'teacher cannot write this',
        })

        assert response.status_code == status.HTTP_200_OK
        after = _item_state([one_off.id])[0]
        assert after['status'] == 'cancelled'
        assert after['scheduled_date'] == before['scheduled_date']
        assert after['admin_notes'] == before['admin_notes']

    def test_waive_limit_applies_per_row_in_request_order(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings, school
    ):
        settings = SchoolSettings.get_settings_for_school(school)
        settings.waive_limit_enabled = True
        settings.waive_limit = 2
        settings.waive_period_type = 'rolling'
        settings.waive_period_months = 4
        settings.save()
        rows = [
            _bulk_item(draft_batch, assigned_student, school_settings, day)
            for day in range(1, settings.waive_limit + 3)
        ]
        ids = [row.id for row in rows]

        response = self._put(authenticated_teacher_client, draft_batch, {'item_ids': ids, 'status': 'waived'})

        assert response.status_code == status.HTTP_200_OK
        statuses = [row['status'] for row in response.data['updated']]
        assert statuses == (
            ['waived'] * settings.waive_limit + ['forfeited'] * (len(ids) - settings.waive_limit)
        )
        converted = [row for row in response.data['updated'] if row['status'] == 'forfeited']
        assert all(row['waive_converted_to_forfeited'] is True for row in converted)
        assert all(row['waive_usage']['remaining'] == 0 for row in converted)
        assert [r['status'] for r in sorted(_item_state(ids), key=lambda r: ids.index(r['id']))] == statuses

    def test_management_cannot_call_teacher_bulk_route(
        self, authenticated_management_client, draft_batch, items
    ):
        ids = [item.id for item in items]
        before = _item_state(ids)

        response = self._put(authenticated_management_client, draft_batch, {'item_ids': ids, 'status': 'cancelled'})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert _item_state(ids) == before


# ---------------------------------------------------------------------------
# MAP-313: a teacher states the actual length of any lesson in a draft batch,
# schedule-generated ones included. Only duration opens up; the recurring
# item's date, time and type stay server-owned.
# ---------------------------------------------------------------------------

from billing.models import RecurringLessonsSchedule


def _schedule(teacher, student, school, school_settings):
    return RecurringLessonsSchedule.objects.create(
        teacher=teacher, student=student, school=school,
        day_of_week=0, start_time=_time(15, 0), duration=Decimal('1.00'),
        lesson_type='online',
        teacher_rate=school_settings.online_teacher_rate,
        student_rate=school_settings.online_student_rate,
        start_date=_date(2026, 1, 5),
    )


def _recurring_item(batch, schedule, day):
    return BatchLessonItem.objects.create(
        batch=batch, student=schedule.student,
        scheduled_date=_date(batch.year, batch.month, day), start_time=schedule.start_time,
        duration=schedule.duration, lesson_type=schedule.lesson_type,
        teacher_rate=schedule.teacher_rate, student_rate=schedule.student_rate,
        status='completed', recurring_schedule=schedule, is_one_off=False,
    )


@pytest.mark.django_db
class TestTeacherRecurringLessonDuration:

    def _put(self, client, batch, item, body):
        return client.put(
            reverse('batch_lesson_item', kwargs={'batch_id': batch.id, 'item_id': item.id}),
            body, format='json',
        )

    @pytest.fixture
    def schedule(self, teacher_user, assigned_student, school, school_settings):
        return _schedule(teacher_user, assigned_student, school, school_settings)

    @pytest.fixture
    def recurring(self, draft_batch, schedule):
        return _recurring_item(draft_batch, schedule, 7)

    def test_recurring_item_duration_is_editable_in_a_draft_batch(
        self, authenticated_teacher_client, draft_batch, recurring, schedule
    ):
        response = self._put(authenticated_teacher_client, draft_batch, recurring, {'duration': '0.75'})

        assert response.status_code == status.HTTP_200_OK, response.data
        recurring.refresh_from_db()
        assert recurring.duration == Decimal('0.75')
        assert recurring.status == 'completed'
        assert Decimal(response.data['duration']) == Decimal('0.75')
        assert Decimal(response.data['teacher_payment']) == recurring.teacher_rate * Decimal('0.75')
        assert Decimal(response.data['student_charge']) == recurring.student_rate * Decimal('0.75')
        # The schedule's planned length is still reported for management review.
        assert Decimal(response.data['schedule_duration']) == schedule.duration

    def test_recurring_item_duration_is_locked_once_submitted(
        self, authenticated_teacher_client, draft_batch, recurring
    ):
        draft_batch.status = 'submitted'
        draft_batch.save(update_fields=['status'])

        response = self._put(authenticated_teacher_client, draft_batch, recurring, {'duration': '0.75'})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == {'error': 'Cannot modify non-draft batch'}
        recurring.refresh_from_db()
        assert recurring.duration == Decimal('1.00')

    def test_recurring_item_keeps_its_date_time_and_type(
        self, authenticated_teacher_client, draft_batch, recurring
    ):
        before = (recurring.scheduled_date, recurring.start_time, recurring.lesson_type)

        response = self._put(authenticated_teacher_client, draft_batch, recurring, {
            'duration': '0.50', 'scheduled_date': '2026-09-28',
            'start_time': '09:00:00', 'lesson_type': 'in_person',
        })

        assert response.status_code == status.HTTP_200_OK, response.data
        recurring.refresh_from_db()
        assert recurring.duration == Decimal('0.50')
        assert (recurring.scheduled_date, recurring.start_time, recurring.lesson_type) == before

    @pytest.mark.parametrize('bad', ['0', '0.00', '-1'])
    def test_non_positive_duration_is_rejected(
        self, authenticated_teacher_client, draft_batch, recurring, bad
    ):
        response = self._put(authenticated_teacher_client, draft_batch, recurring, {'duration': bad})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'duration' in response.data
        recurring.refresh_from_db()
        assert recurring.duration == Decimal('1.00')

    def test_schedule_duration_is_null_for_a_one_off(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings
    ):
        one_off = _bulk_item(draft_batch, assigned_student, school_settings, 8, is_one_off=True)

        response = self._put(authenticated_teacher_client, draft_batch, one_off, {'duration': '1.50'})

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data['schedule_duration'] is None
        assert Decimal(response.data['duration']) == Decimal('1.50')

    def test_schedule_duration_is_null_when_the_schedule_was_deleted(
        self, authenticated_teacher_client, draft_batch, recurring, schedule
    ):
        schedule.delete()
        recurring.refresh_from_db()
        assert recurring.recurring_schedule_id is None

        response = self._put(authenticated_teacher_client, draft_batch, recurring, {'teacher_notes': 'ok'})

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data['schedule_duration'] is None


# ---------------------------------------------------------------------------
# MAP-312: batch_submit refuses a draft that still has past Confirmed lessons.
# "Today" is the school's date in America/Toronto (owner ruling 2026-11-02),
# the same rule the UI applies with the browser's local date.
# ---------------------------------------------------------------------------

from datetime import datetime as _datetime, timedelta as _timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.utils import timezone

SCHOOL_TZ = ZoneInfo('America/Toronto')


def _school_today():
    return timezone.localdate(timezone=SCHOOL_TZ)


def _dated_item(batch, student, school_settings, scheduled_date, status):
    return BatchLessonItem.objects.create(
        batch=batch, student=student,
        scheduled_date=scheduled_date, start_time=_time(15, 0),
        duration=Decimal('1.0'), lesson_type='online',
        teacher_rate=school_settings.online_teacher_rate,
        student_rate=school_settings.online_student_rate,
        status=status,
    )


@pytest.mark.django_db
class TestBatchSubmitUnresolvedPast:

    @pytest.fixture
    def add_item(self, draft_batch, assigned_student, school_settings):
        # A student's first item is auto-promoted to 'trial' (BatchLessonItem.save);
        # create one up front so every item a test adds keeps its status.
        _dated_item(draft_batch, assigned_student, school_settings, _school_today(), 'completed')

        def add(scheduled_date, status):
            return _dated_item(draft_batch, assigned_student, school_settings, scheduled_date, status)
        return add

    def _submit(self, client, batch):
        return client.post(reverse('batch_submit', kwargs={'batch_id': batch.id}), format='json')

    def test_past_confirmed_item_blocks_submit_and_batch_stays_draft(
        self, authenticated_teacher_client, draft_batch, add_item
    ):
        today = _school_today()
        past = add_item(today - _timedelta(days=1), 'confirmed')
        add_item(today - _timedelta(days=2), 'completed')

        response = self._submit(authenticated_teacher_client, draft_batch)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            'error': 'Mark past lessons Completed or Cancelled before submitting',
            'unresolved_item_ids': [past.id],
        }
        draft_batch.refresh_from_db()
        assert draft_batch.status == 'draft'
        assert draft_batch.submitted_at is None

    def test_unresolved_item_ids_are_ascending(
        self, authenticated_teacher_client, draft_batch, add_item
    ):
        # Date order is the reverse of id order, so a date-ordered list would
        # fail here; ascending ids is the contract (W2-L2 fold).
        today = _school_today()
        later_dated = add_item(today - _timedelta(days=1), 'confirmed')
        earlier_dated = add_item(today - _timedelta(days=5), 'confirmed')
        assert later_dated.id < earlier_dated.id

        response = self._submit(authenticated_teacher_client, draft_batch)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()['unresolved_item_ids'] == [later_dated.id, earlier_dated.id]

    def test_confirmed_items_today_or_later_submit(
        self, authenticated_teacher_client, draft_batch, add_item
    ):
        today = _school_today()
        add_item(today, 'confirmed')
        add_item(today + _timedelta(days=1), 'confirmed')

        response = self._submit(authenticated_teacher_client, draft_batch)

        assert response.status_code == status.HTTP_200_OK, response.data
        draft_batch.refresh_from_db()
        assert draft_batch.status == 'submitted'

    def test_lesson_dated_today_submits_in_the_toronto_evening(
        self, authenticated_teacher_client, draft_batch, add_item
    ):
        # 23:30 in Toronto is already the next day in UTC; the lesson is still "today".
        evening = _datetime(2026, 11, 2, 23, 30, tzinfo=SCHOOL_TZ)
        assert evening.astimezone(ZoneInfo('UTC')).date() > evening.date()
        add_item(evening.date(), 'confirmed')

        with mock.patch('django.utils.timezone.now', return_value=evening):
            response = self._submit(authenticated_teacher_client, draft_batch)

        assert response.status_code == status.HTTP_200_OK, response.data
        draft_batch.refresh_from_db()
        assert draft_batch.status == 'submitted'

    # Every non-confirmed status: only 'confirmed' blocks (W2-L2 fold).
    @pytest.mark.parametrize('resolved_status', [
        'completed', 'cancelled', 'forfeited', 'waived', 'teacher_cancelled', 'promo', 'trial',
    ])
    def test_resolved_past_items_do_not_block(
        self, authenticated_teacher_client, draft_batch, add_item, resolved_status
    ):
        add_item(_school_today() - _timedelta(days=1), resolved_status)

        response = self._submit(authenticated_teacher_client, draft_batch)

        assert response.status_code == status.HTTP_200_OK, response.data
