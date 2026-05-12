"""
Integration tests for billable contact validation across the system.

Tests the multi-layer validation strategy:
- Layer 1: Creation validation (serializers)
- Layer 2: Invoice submission validation (views)
- Layer 3: Auto-created student placeholders

Location: tests/integration/billing/test_billable_contact_validation.py
"""
import pytest
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from billing.models import BillableContact, Lesson, Invoice

User = get_user_model()


@pytest.fixture
def student_with_complete_contact(school, db):
    """Create a student with complete billing contact"""
    student = User.objects.create_user(
        email='student_complete@test.com',
        password='testpass123',
        first_name='Student',
        last_name='Test',
        user_type='student',
        school=school,
        is_approved=True
    )
    BillableContact.objects.create(
        student=student,
        school=school,
        contact_type='parent',
        first_name='Parent',
        last_name='Test',
        email='parent@test.com',
        phone='416-555-0100',
        street_address='123 Test St',
        city='Toronto',
        province='ON',
        postal_code='M5H 2N2',
        is_primary=True
    )
    return student


@pytest.fixture
def student_with_incomplete_contact(school, db):
    """Create a student with incomplete billing contact (missing fields)"""
    student = User.objects.create_user(
        email='student_incomplete@test.com',
        password='testpass123',
        first_name='Incomplete',
        last_name='Student',
        user_type='student',
        school=school,
        is_approved=True
    )
    BillableContact.objects.create(
        student=student,
        school=school,
        contact_type='parent',
        first_name='INCOMPLETE',
        last_name='INCOMPLETE',
        email='incomplete@test.com',
        phone='INCOMPLETE',
        street_address='INCOMPLETE',
        city='',  # Missing
        province='XX',  # Incomplete placeholder
        postal_code='',  # Missing
        is_primary=True
    )
    return student


@pytest.mark.django_db
class TestStudentCreationValidation:
    """Test Layer 1: Creation validation"""

    def test_create_student_with_complete_billing_contact_success(self, api_client, management_user):
        """✅ Should successfully create student with all required fields"""
        api_client.force_authenticate(user=management_user)

        data = {
            'email': 'newstudent@test.com',
            'first_name': 'New',
            'last_name': 'Student',
            'billing_contact': {
                'contact_type': 'parent',
                'first_name': 'Parent',
                'last_name': 'Name',
                'email': 'parent@test.com',
                'phone': '416-555-0101',
                'street_address': '456 Main St',
                'city': 'Toronto',
                'province': 'ON',
                'postal_code': 'M4B 1B3'
            }
        }

        response = api_client.post('/api/billing/management/students/', data, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(email='newstudent@test.com').exists()

        student = User.objects.get(email='newstudent@test.com')
        assert student.billable_contacts.count() == 1

        contact = student.billable_contacts.first()
        assert contact.city == 'Toronto'
        assert contact.province == 'ON'
        assert contact.postal_code == 'M4B 1B3'
        assert contact.is_primary is True

    def test_create_student_missing_city_fails(self, api_client, management_user):
        """❌ Should fail when city is missing"""
        api_client.force_authenticate(user=management_user)

        data = {
            'email': 'newstudent2@test.com',
            'first_name': 'New',
            'last_name': 'Student',
            'billing_contact': {
                'contact_type': 'parent',
                'first_name': 'Parent',
                'last_name': 'Name',
                'email': 'parent@test.com',
                'phone': '416-555-0101',
                'street_address': '456 Main St',
                # 'city': missing
                'province': 'ON',
                'postal_code': 'M4B 1B3'
            }
        }

        response = api_client.post('/api/billing/management/students/', data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'city' in str(response.data).lower() or 'required' in str(response.data).lower()

    def test_create_student_missing_province_fails(self, api_client, management_user):
        """❌ Should fail when province is missing"""
        api_client.force_authenticate(user=management_user)

        data = {
            'email': 'newstudent3@test.com',
            'first_name': 'New',
            'last_name': 'Student',
            'billing_contact': {
                'contact_type': 'parent',
                'first_name': 'Parent',
                'last_name': 'Name',
                'email': 'parent@test.com',
                'phone': '416-555-0101',
                'street_address': '456 Main St',
                'city': 'Toronto',
                # 'province': missing
                'postal_code': 'M4B 1B3'
            }
        }

        response = api_client.post('/api/billing/management/students/', data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'province' in str(response.data).lower() or 'required' in str(response.data).lower()

    def test_create_student_invalid_postal_code_fails(self, api_client, management_user):
        """❌ Should fail with invalid Canadian postal code format"""
        api_client.force_authenticate(user=management_user)

        data = {
            'email': 'newstudent4@test.com',
            'first_name': 'New',
            'last_name': 'Student',
            'billing_contact': {
                'contact_type': 'parent',
                'first_name': 'Parent',
                'last_name': 'Name',
                'email': 'parent@test.com',
                'phone': '416-555-0101',
                'street_address': '456 Main St',
                'city': 'Toronto',
                'province': 'ON',
                'postal_code': '12345'  # Invalid - not Canadian format
            }
        }

        response = api_client.post('/api/billing/management/students/', data, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'postal' in str(response.data).lower()


@pytest.mark.django_db
class TestInvoiceSubmissionValidation:
    """Test Layer 2: Invoice submission validation"""

    def test_submit_invoice_with_complete_contact_success(
        self, api_client, teacher_user, student_with_complete_contact
    ):
        """✅ Should successfully submit invoice when student has complete billing contact"""
        api_client.force_authenticate(user=teacher_user)

        data = {
            'lessons': [
                {
                    'student_name': 'Student Test',
                    'student_email': student_with_complete_contact.email,
                    'scheduled_date': '2026-01-15T14:00:00Z',
                    'duration': 1.0,
                    'lesson_type': 'in_person',
                    'teacher_notes': 'Test lesson'
                }
            ],
            'due_date': '2026-02-15T00:00:00Z'
        }

        response = api_client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json'
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Invoice.objects.filter(teacher=teacher_user).exists()

    def test_submit_invoice_with_incomplete_contact_fails(
        self, api_client, teacher_user, student_with_incomplete_contact
    ):
        """❌ Should fail when student has incomplete billing contact"""
        api_client.force_authenticate(user=teacher_user)

        data = {
            'lessons': [
                {
                    'student_name': 'Incomplete Student',
                    'student_email': student_with_incomplete_contact.email,
                    'scheduled_date': '2026-01-15T14:00:00Z',
                    'duration': 1.0,
                    'lesson_type': 'in_person',
                    'teacher_notes': 'Test lesson'
                }
            ],
            'due_date': '2026-02-15T00:00:00Z'
        }

        response = api_client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_text = str(response.data).lower()
        assert 'incomplete' in response_text or 'missing' in response_text
        assert 'city' in response_text or 'province' in response_text

    def test_submit_invoice_error_message_includes_student_email(
        self, api_client, teacher_user, student_with_incomplete_contact
    ):
        """✅ Error message should include student email for easy identification"""
        api_client.force_authenticate(user=teacher_user)

        data = {
            'lessons': [
                {
                    'student_name': 'Incomplete Student',
                    'student_email': student_with_incomplete_contact.email,
                    'scheduled_date': '2026-01-15T14:00:00Z',
                    'duration': 1.0,
                    'lesson_type': 'in_person'
                }
            ],
            'due_date': '2026-02-15T00:00:00Z'
        }

        response = api_client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json'
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert student_with_incomplete_contact.email in str(response.data)


@pytest.mark.django_db
class TestAutoCreatedStudentPlaceholders:
    """Test Layer 3: Auto-created student placeholders"""

    def test_new_student_gets_placeholder_contact(self, api_client, teacher_user):
        """✅ When teacher creates new student via invoice, should get placeholder contact"""
        api_client.force_authenticate(user=teacher_user)

        new_student_email = 'brandnew@test.com'
        data = {
            'lessons': [
                {
                    'student_name': 'Brand New Student',
                    'student_email': new_student_email,
                    'scheduled_date': '2026-01-15T14:00:00Z',
                    'duration': 1.0,
                    'lesson_type': 'in_person'
                }
            ],
            'due_date': '2026-02-15T00:00:00Z'
        }

        # This should fail validation due to new student having placeholder contact
        response = api_client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json'
        )

        # Student should still be created
        assert User.objects.filter(email=new_student_email).exists()
        student = User.objects.get(email=new_student_email)

        # Should have a placeholder billable contact
        assert student.billable_contacts.count() == 1
        contact = student.billable_contacts.first()
        assert contact.first_name == 'INCOMPLETE'
        assert contact.province == 'XX'

    def test_placeholder_can_be_updated_to_complete(
        self, api_client, management_user, student_with_incomplete_contact
    ):
        """✅ Management should be able to update incomplete contact to complete"""
        api_client.force_authenticate(user=management_user)

        contact = student_with_incomplete_contact.billable_contacts.first()

        update_data = {
            'first_name': 'Complete',
            'last_name': 'Parent',
            'email': 'complete@parent.com',
            'phone': '416-555-0200',
            'street_address': '789 Complete Ave',
            'city': 'Toronto',
            'province': 'ON',
            'postal_code': 'M6K 3P6',
            'is_primary': True
        }

        response = api_client.put(
            f'/api/billing/management/billable-contacts/{contact.id}/',
            update_data,
            format='json'
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify update
        contact.refresh_from_db()
        assert contact.city == 'Toronto'
        assert contact.province == 'ON'
        assert contact.first_name == 'Complete'
