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

from billing.models import Invoice, Lesson, BatchLessonItem, MonthlyInvoiceBatch
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
        assert 'Teacher access required' in response.data['error']

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

LEGACY_ROUTE_PATHS = [
    'teachers', 'students', 'lessons',
    'teacher_pk', 'student_pk', 'lesson_pk', 'invoice_pk',
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
    }


@pytest.mark.django_db
class TestLegacyGenericRoutesRemoved:
    """MAP-178 acceptance: each of the seven routes -> 404 for every role."""

    @pytest.mark.parametrize('route_name', LEGACY_ROUTE_NAMES)
    def test_legacy_route_name_is_not_registered(self, route_name):
        """The URL name is gone from billing/urls.py."""
        with pytest.raises(NoReverseMatch):
            reverse(route_name, kwargs={'pk': 1} if route_name.endswith('_detail') else None)

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


@pytest.mark.django_db
class TestTeacherInvoiceListIsReadOnly:
    """P0 audit 2026-09-09: invoices/teacher/ lists only; invoices are created
    through submit-lessons/. The former POST branch could not create a row once
    MAP-178 made teacher/payment_balance read-only (IntegrityError -> 500)."""

    @pytest.mark.parametrize('client_fixture', ['authenticated_teacher_client', 'authenticated_management_client'])
    def test_post_is_not_allowed_and_creates_nothing(self, request, client_fixture, school_settings):
        client = request.getfixturevalue(client_fixture)
        before = Invoice.objects.count()

        response = client.post(
            reverse('teacher_invoice_list'),
            {'invoice_type': 'teacher_payment', 'due_date': '2026-09-30T00:00:00Z', 'lessons': []},
            format='json',
        )

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert Invoice.objects.count() == before

    def test_get_still_lists_for_teacher(self, authenticated_teacher_client, school_settings):
        response = authenticated_teacher_client.get(reverse('teacher_invoice_list'))
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)


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

    @pytest.mark.parametrize('bad_status', ['waived', 'trial', 'requested', 'forfeited'])
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

    def test_cancelled_status_is_stored(
        self, authenticated_teacher_client, draft_batch, assigned_student, school_settings
    ):
        response = self._post(authenticated_teacher_client, draft_batch, _live_payload(assigned_student, status='cancelled'))

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert BatchLessonItem.objects.get(pk=response.data['id']).status == 'cancelled'

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
