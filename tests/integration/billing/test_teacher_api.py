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

from billing.models import Invoice, Lesson

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
