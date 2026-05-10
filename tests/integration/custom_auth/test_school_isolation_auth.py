"""
Integration tests for cross-school isolation at the auth/authorization layer.
Requirement: TST-05

Companion to tests/integration/billing/test_school_isolation.py:
  - That file tests ORM-layer isolation (queries filter by school).
  - This file tests AUTH-layer isolation (authenticated School A management
    cannot touch School B data via the live HTTP endpoints).

SEC-04 invariant: cross-school access returns 404 (not 403, not 200) so
attackers cannot enumerate row existence in other schools.
"""
import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from django.contrib.auth import get_user_model
from billing.models import Invoice

User = get_user_model()


@pytest.mark.django_db
class TestAuthSchoolIsolation:
    """
    SEC-04: Auth-layer isolation tests.

    All tests authenticate as School A management and attempt to access School B
    data. Every attempt must return 404 — not 403, not 200. The 404 is intentional
    (security best practice: don't reveal row existence to cross-school requests).
    """

    @pytest.fixture
    def school2_management(self, second_school, db):
        return User.objects.create_user(
            email='mgmt_s2@school2.com',
            password='testpass123',
            user_type='management',
            school=second_school,
            is_approved=True,
        )

    @pytest.fixture
    def school2_teacher(self, second_school, db):
        return User.objects.create_user(
            email='teacher_s2@school2.com',
            password='testpass123',
            user_type='teacher',
            school=second_school,
            hourly_rate=Decimal('70.00'),
            is_approved=True,
        )

    # -------------------------------------------------------------------------
    # Task 1: Cross-school write/read-attempt tests
    # -------------------------------------------------------------------------

    def test_school1_mgmt_cannot_delete_school2_user(
        self, api_client, management_user, school2_teacher
    ):
        """
        SEC-04 (T-05-16): School A management cannot delete a user belonging to
        School B. The endpoint must return 404 and leave the victim row intact.
        """
        api_client.force_authenticate(user=management_user)
        url = reverse('management_delete_user', kwargs={'pk': school2_teacher.id})
        response = api_client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        # Victim row was NOT deleted
        assert User.objects.filter(id=school2_teacher.id).exists() is True

    def test_school1_mgmt_cannot_approve_school2_invoice(
        self, api_client, management_user, second_school, school2_teacher
    ):
        """
        SEC-04 (T-05-16): School A management cannot approve a teacher-payment
        invoice belonging to School B. Must return 404; invoice status must stay
        'pending' after the request.
        """
        invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=school2_teacher,
            school=second_school,
            status='pending',
            payment_balance=Decimal('100.00'),
            total_amount=Decimal('100.00'),
        )

        api_client.force_authenticate(user=management_user)
        url = reverse('approve_teacher_invoice', kwargs={'invoice_id': invoice.id})
        response = api_client.post(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        invoice.refresh_from_db()
        assert invoice.status == 'pending'

    def test_school1_mgmt_cannot_view_school2_teacher(
        self, api_client, management_user, school2_teacher
    ):
        """
        SEC-04 (T-05-15): School A management cannot read a teacher profile
        belonging to School B via teacher_detail. Must return 404.

        Pins the school filter at billing/views/management.py:642:
            User.objects.get(pk=pk, user_type='teacher', school=request.user.school)
        If the filter is removed, the response would be 200 and this test fails.
        """
        api_client.force_authenticate(user=management_user)
        url = reverse('teacher_detail', kwargs={'pk': school2_teacher.id})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    # -------------------------------------------------------------------------
    # Task 2: Student-detail, listing-leakage, and user_profile tests
    # -------------------------------------------------------------------------

    def test_school1_mgmt_cannot_view_school2_student(
        self, api_client, management_user, second_school
    ):
        """
        SEC-04 (T-05-15): School A management cannot read a student profile
        belonging to School B via management_student_detail. Must return 404.

        NOTE: There is NO separate Student model — "students" are User rows with
        user_type='student'. The endpoint does:
            User.objects.get(pk=pk, user_type='student', school=request.user.school)
        """
        school2_student = User.objects.create_user(
            email='student_s2@school2.com',
            password='studentpass',
            user_type='student',
            school=second_school,
            is_approved=True,
        )

        api_client.force_authenticate(user=management_user)
        url = reverse('management_student_detail', kwargs={'pk': school2_student.id})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        # Row was not deleted
        assert User.objects.filter(id=school2_student.id, user_type='student').exists() is True

    def test_school1_mgmt_user_list_excludes_school2_users(
        self, api_client, management_user, second_school, school2_teacher, school2_management
    ):
        """
        SEC-04 (T-05-17): The management_all_users listing must NOT leak School B
        rows. school2_teacher and school2_management are injected to ensure School B
        rows exist in the DB — they must not appear in the response payload.
        """
        api_client.force_authenticate(user=management_user)
        url = reverse('management_all_users')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK

        emails = [
            u.get('email')
            for u in (
                response.data
                if isinstance(response.data, list)
                else response.data.get('results', [])
            )
        ]

        assert 'teacher_s2@school2.com' not in emails
        assert 'mgmt_s2@school2.com' not in emails

    def test_user_profile_returns_only_own_school_user(
        self, api_client, management_user, school2_management
    ):
        """
        SEC-04 (T-05-18): user_profile must return only the authenticated user's
        own data — not any other user's data, regardless of school.

        school2_management is injected to ensure a School B user exists. The
        response must contain management_user's email, not school2_management's.
        """
        api_client.force_authenticate(user=management_user)
        url = reverse('user_profile')
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['user']['email'] == management_user.email
        assert response.data['user']['email'] != school2_management.email
