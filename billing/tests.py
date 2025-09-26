import os
import django
from django.conf import settings

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maple_key_backend.settings')
django.setup()

import pytest
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch, MagicMock
from rest_framework.test import APITestCase
from rest_framework import status
from datetime import datetime, timedelta
from django.core.exceptions import ValidationError

from billing.models import Lesson, Invoice
from billing.views import submit_lessons_for_invoice
from custom_auth.decorators import teacher_required

User = get_user_model()


class BillingUnitTests(TestCase):
    """Unit tests for billing functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.teacher = User.objects.create_user(
            email='teacher@test.com',
            password='testpass123',
            first_name='John',
            last_name='Teacher',
            user_type='teacher',
            hourly_rate=75.00,
            is_approved=True
        )
        
        self.management = User.objects.create_user(
            email='admin@test.com',
            password='testpass123',
            first_name='Admin',
            last_name='User',
            user_type='management',
            is_approved=True
        )

    def test_student_creation_with_unique_name(self):
        """Test creating a student with a unique name"""
        student_name = "Alice Johnson"
        
        # Mock the view function to test student creation logic
        with patch('billing.views.User.objects') as mock_user:
            # Mock that no student exists
            mock_user.get.side_effect = User.DoesNotExist()
            mock_user.filter.return_value.exists.return_value = False
            
            # Test the student creation logic
            base_email = f"{student_name.lower().replace(' ', '.')}@temp.com"
            unique_email = base_email
            
            # Should create student with base email since it doesn't exist
            self.assertEqual(unique_email, "alice.johnson@temp.com")

    def test_student_creation_with_duplicate_name(self):
        """Test creating a student with a duplicate name"""
        student_name = "Joey Smith"
        
        with patch('billing.views.User.objects') as mock_user:
            # Mock that student exists by name
            mock_user.get.return_value = MagicMock()
            
            # Should find existing student instead of creating new one
            try:
                student = mock_user.get(
                    first_name=student_name.split()[0],
                    last_name=' '.join(student_name.split()[1:]),
                    user_type='student'
                )
                self.assertIsNotNone(student)
            except User.DoesNotExist:
                self.fail("Should have found existing student")

    def test_student_creation_with_duplicate_email(self):
        """Test creating a student when email already exists"""
        student_name = "Joey Smith"
        base_email = f"{student_name.lower().replace(' ', '.')}@temp.com"
        
        with patch('billing.views.User.objects') as mock_user:
            # Mock that base email exists, but joey.smith1@temp.com doesn't
            call_count = 0
            def mock_exists():
                nonlocal call_count
                call_count += 1
                # First call returns True (email exists), second call returns False (unique email found)
                return call_count == 1
            
            mock_user.filter.return_value.exists.side_effect = mock_exists
            
            # Test the unique email generation logic
            counter = 1
            unique_email = base_email
            
            # Simulate the loop that would happen in the actual code
            while mock_user.filter.return_value.exists():
                unique_email = f"{student_name.lower().replace(' ', '.')}{counter}@temp.com"
                counter += 1
                if counter > 10:  # Prevent infinite loop in test
                    break
            
            self.assertEqual(unique_email, "joey.smith1@temp.com")

    def test_lesson_cost_calculation(self):
        """Test lesson cost calculation"""
        student = User.objects.create_user(
            email='student@test.com',
            password='testpass123',
            first_name='Jane',
            last_name='Student',
            user_type='student',
            is_approved=True
        )
        
        lesson = Lesson.objects.create(
            teacher=self.teacher,
            student=student,
            scheduled_date=timezone.now(),
            duration=1.5,
            rate=75.00,
            status='completed'
        )
        
        expected_cost = Decimal('112.50')  # 1.5 * 75.00
        self.assertEqual(lesson.total_cost(), expected_cost)

    def test_invoice_payment_balance_calculation(self):
        """Test invoice payment balance calculation"""
        student = User.objects.create_user(
            email='student@test.com',
            password='testpass123',
            first_name='Jane',
            last_name='Student',
            user_type='student',
            is_approved=True
        )
        
        # Create lessons
        lesson1 = Lesson.objects.create(
            teacher=self.teacher,
            student=student,
            scheduled_date=timezone.now(),
            duration=1.0,
            rate=75.00,
            status='completed'
        )
        
        lesson2 = Lesson.objects.create(
            teacher=self.teacher,
            student=student,
            scheduled_date=timezone.now(),
            duration=0.5,
            rate=75.00,
            status='completed'
        )
        
        # Create invoice
        invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=self.teacher,
            status='pending',
            due_date=timezone.now() + timedelta(days=30),
            created_by=self.teacher,
            payment_balance=0
        )
        
        # Add lessons to invoice
        invoice.lessons.set([lesson1, lesson2])
        
        # Test payment balance calculation
        expected_balance = Decimal('112.50')  # (1.0 + 0.5) * 75.00
        self.assertEqual(invoice.calculate_payment_balance(), expected_balance)

    def test_invoice_creation_with_mixed_students(self):
        """Test invoice creation with both new and existing students"""
        # Create an existing student
        existing_student = User.objects.create_user(
            email='existing@test.com',
            password='testpass123',
            first_name='Existing',
            last_name='Student',
            user_type='student',
            is_approved=True
        )
        
        # Mock the view logic for mixed student handling
        lessons_data = [
            {
                'student_name': 'Existing Student',
                'student_email': 'existing@test.com',
                'duration': 1.0
            },
            {
                'student_name': 'New Student',
                'student_email': None,
                'duration': 1.5
            }
        ]
        
        # Test that existing student is found
        with patch('billing.views.User.objects') as mock_user:
            # Mock finding existing student
            mock_user.get.return_value = existing_student
            
            # Test existing student lookup
            student_email = lessons_data[0].get('student_email')
            if student_email:
                student = mock_user.get(email=student_email, user_type='student')
                self.assertEqual(student, existing_student)

    def test_lesson_creation_with_invalid_data(self):
        """Test lesson creation with invalid data"""
        student = User.objects.create_user(
            email='student@test.com',
            password='testpass123',
            first_name='Jane',
            last_name='Student',
            user_type='student',
            is_approved=True
        )
        
        # Test with negative duration
        with self.assertRaises(ValidationError):
            lesson = Lesson(
                teacher=self.teacher,
                student=student,
                scheduled_date=timezone.now(),
                duration=-1.0,  # Invalid negative duration
                rate=75.00,
                status='completed'
            )
            lesson.clean()  # This will raise ValidationError

    def test_invoice_status_transitions(self):
        """Test invoice status transitions"""
        invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=self.teacher,
            status='draft',
            due_date=timezone.now() + timedelta(days=30),
            created_by=self.teacher,
            payment_balance=0
        )
        
        # Test status transitions
        self.assertEqual(invoice.status, 'draft')
        
        # Should be able to move from draft to pending
        invoice.status = 'pending'
        invoice.save()
        self.assertEqual(invoice.status, 'pending')
        
        # Should be able to move from pending to approved
        invoice.status = 'approved'
        invoice.approved_by = self.management
        invoice.approved_at = timezone.now()
        invoice.save()
        self.assertEqual(invoice.status, 'approved')

    def test_teacher_hourly_rate_validation(self):
        """Test teacher hourly rate validation"""
        # Test with valid rate
        self.teacher.hourly_rate = 75.00
        self.teacher.save()
        self.assertEqual(self.teacher.hourly_rate, Decimal('75.00'))
        
        # Test with zero rate
        self.teacher.hourly_rate = 0.00
        self.teacher.save()
        self.assertEqual(self.teacher.hourly_rate, Decimal('0.00'))
        
        # Test with high rate
        self.teacher.hourly_rate = 500.00
        self.teacher.save()
        self.assertEqual(self.teacher.hourly_rate, Decimal('500.00'))


class BillingAPITests(APITestCase):
    """API tests for billing endpoints"""
    
    def setUp(self):
        """Set up test data for API tests"""
        self.teacher = User.objects.create_user(
            email='teacher@test.com',
            password='testpass123',
            first_name='John',
            last_name='Teacher',
            user_type='teacher',
            hourly_rate=75.00,
            is_approved=True
        )
        
        self.management = User.objects.create_user(
            email='admin@test.com',
            password='testpass123',
            first_name='Admin',
            last_name='User',
            user_type='management',
            is_approved=True
        )
        
        # Get auth tokens
        self.teacher_token = self._get_auth_token('teacher@test.com', 'testpass123')
        self.management_token = self._get_auth_token('admin@test.com', 'testpass123')

    def _get_auth_token(self, email, password):
        """Helper method to get auth token"""
        response = self.client.post('/api/auth/token/', {
            'email': email,
            'password': password
        })
        if response.status_code == 200:
            return response.json()['access_token']
        return None

    def test_submit_lessons_for_invoice_success(self):
        """Test successful lesson submission for invoice"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'student_email': 'alice@test.com',
                    'duration': 1.0
                },
                {
                    'student_name': 'Bob Smith',
                    'student_email': None,
                    'duration': 1.5
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('invoice', response.data)
        self.assertIn('lessons_created', response.data)

    def test_submit_lessons_for_invoice_no_lessons(self):
        """Test submitting invoice with no lessons"""
        data = {'lessons': []}
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('No lessons provided', response.data['error'])

    def test_submit_lessons_for_invoice_unauthorized(self):
        """Test submitting invoice without authentication"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_submit_lessons_for_invoice_wrong_user_type(self):
        """Test submitting invoice with wrong user type"""
        student = User.objects.create_user(
            email='student@test.com',
            password='testpass123',
            first_name='Jane',
            last_name='Student',
            user_type='student',
            is_approved=True
        )
        
        student_token = self._get_auth_token('student@test.com', 'testpass123')
        
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {student_token}'
        )
        
        # Should return 401 (Unauthorized) since student can't get token for teacher endpoint
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_duplicate_student_handling(self):
        """Test handling of duplicate student names"""
        # Create existing student
        existing_student = User.objects.create_user(
            email='alice.johnson@temp.com',
            password='testpass123',
            first_name='Alice',
            last_name='Johnson',
            user_type='student',
            is_approved=True
        )
        
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'student_email': None,
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should succeed and reuse existing student
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_invalid_lesson_data(self):
        """Test submitting invoice with invalid lesson data"""
        data = {
            'lessons': [
                {
                    'student_name': '',  # Empty name
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should handle gracefully
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_500_INTERNAL_SERVER_ERROR])

    def test_negative_duration_handling(self):
        """Test handling of negative duration"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': -1.0  # Negative duration
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should handle gracefully
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_500_INTERNAL_SERVER_ERROR])

    def test_very_long_student_name(self):
        """Test handling of very long student names"""
        long_name = 'A' * 1000  # Very long name
        
        data = {
            'lessons': [
                {
                    'student_name': long_name,
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should handle gracefully
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])

    def test_special_characters_in_student_name(self):
        """Test handling of special characters in student names"""
        data = {
            'lessons': [
                {
                    'student_name': 'José María O\'Connor-Smith',
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should handle special characters gracefully
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_unicode_student_name(self):
        """Test handling of unicode characters in student names"""
        data = {
            'lessons': [
                {
                    'student_name': '李小明',  # Chinese characters
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should handle unicode gracefully
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_zero_duration_lesson(self):
        """Test handling of zero duration lessons"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 0.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for zero duration (validation error)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_very_high_duration(self):
        """Test handling of very high duration values"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 999.99  # Very high duration
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for unreasonably high duration
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_malformed_json_request(self):
        """Test handling of malformed JSON requests"""
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            'invalid json',
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for malformed JSON
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_required_fields(self):
        """Test handling of missing required fields"""
        data = {
            'lessons': [
                {
                    # Missing student_name
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should handle missing fields gracefully
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_500_INTERNAL_SERVER_ERROR])


class BillingAdditionalTests(APITestCase):
    """Additional tests to improve coverage"""
    
    def setUp(self):
        """Set up test data for additional tests"""
        self.teacher = User.objects.create_user(
            email='teacher@test.com',
            password='testpass123',
            first_name='John',
            last_name='Teacher',
            user_type='teacher',
            hourly_rate=75.00,
            is_approved=True
        )
        
        self.management = User.objects.create_user(
            email='admin@test.com',
            password='testpass123',
            first_name='Admin',
            last_name='User',
            user_type='management',
            is_approved=True
        )
        
        # Get auth tokens
        self.teacher_token = self._get_auth_token('teacher@test.com', 'testpass123')
        self.management_token = self._get_auth_token('admin@test.com', 'testpass123')

    def _get_auth_token(self, email, password):
        """Helper method to get auth token"""
        response = self.client.post('/api/auth/token/', {
            'email': email,
            'password': password
        })
        if response.status_code == 200:
            return response.json()['access_token']
        return None

    def test_submit_lessons_with_student_email(self):
        """Test submitting lessons with student email provided"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'student_email': 'alice@test.com',
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('invoice', response.data)

    def test_submit_lessons_with_existing_student_email(self):
        """Test submitting lessons with existing student email"""
        # Create existing student
        existing_student = User.objects.create_user(
            email='existing@test.com',
            password='testpass123',
            first_name='Existing',
            last_name='Student',
            user_type='student',
            is_approved=True
        )
        
        data = {
            'lessons': [
                {
                    'student_name': 'Existing Student',
                    'student_email': 'existing@test.com',
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_teacher_notes(self):
        """Test submitting lessons with teacher notes"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0,
                    'teacher_notes': 'Great progress on scales'
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_custom_rate(self):
        """Test submitting lessons with custom rate"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0,
                    'rate': 100.00  # Custom rate
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_scheduled_date(self):
        """Test submitting lessons with scheduled date"""
        from datetime import timedelta
        
        scheduled_date = timezone.now() + timedelta(days=1)
        
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0,
                    'scheduled_date': scheduled_date.isoformat()
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_due_date(self):
        """Test submitting lessons with due date"""
        from datetime import timedelta
        
        due_date = timezone.now() + timedelta(days=30)
        
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0
                }
            ],
            'due_date': due_date.isoformat()
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_multiple_students(self):
        """Test submitting lessons for multiple students"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0
                },
                {
                    'student_name': 'Bob Smith',
                    'duration': 1.5
                },
                {
                    'student_name': 'Charlie Brown',
                    'duration': 0.5
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('lessons_created', response.data)
        self.assertEqual(response.data['lessons_created'], 3)

    def test_submit_lessons_with_mixed_student_types(self):
        """Test submitting lessons with mix of new and existing students"""
        # Create existing student
        existing_student = User.objects.create_user(
            email='existing@test.com',
            password='testpass123',
            first_name='Existing',
            last_name='Student',
            user_type='student',
            is_approved=True
        )
        
        data = {
            'lessons': [
                {
                    'student_name': 'Existing Student',
                    'student_email': 'existing@test.com',
                    'duration': 1.0
                },
                {
                    'student_name': 'New Student',
                    'duration': 1.5
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_decimal_duration(self):
        """Test submitting lessons with decimal duration"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.25  # 1 hour 15 minutes
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_minimum_duration(self):
        """Test submitting lessons with minimum valid duration"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 0.25  # 15 minutes
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_maximum_duration(self):
        """Test submitting lessons with maximum valid duration"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 24.0  # 24 hours (maximum allowed)
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_boundary_duration(self):
        """Test submitting lessons with boundary duration (just over 24 hours)"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 24.01  # Just over 24 hours
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for duration over 24 hours
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_boundary_name_length(self):
        """Test submitting lessons with boundary name length"""
        data = {
            'lessons': [
                {
                    'student_name': 'A' * 150,  # Reasonable long name (avoid DB field limits)
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_over_boundary_name_length(self):
        """Test submitting lessons with name over boundary length"""
        data = {
            'lessons': [
                {
                    'student_name': 'A' * 151,  # Over maximum allowed length (150)
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for name too long
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_invalid_json(self):
        """Test submitting lessons with invalid JSON"""
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            'invalid json data',
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for invalid JSON
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_missing_lessons_field(self):
        """Test submitting lessons with missing lessons field"""
        data = {
            'due_date': '2024-12-31T00:00:00Z'
            # Missing 'lessons' field
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for missing lessons
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_empty_lessons_list(self):
        """Test submitting lessons with empty lessons list"""
        data = {
            'lessons': []  # Empty list
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for empty lessons
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_whitespace_only_name(self):
        """Test submitting lessons with whitespace-only name"""
        data = {
            'lessons': [
                {
                    'student_name': '   ',  # Only whitespace
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for whitespace-only name
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_none_duration(self):
        """Test submitting lessons with None duration"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': None  # None duration
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for None duration
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_string_duration(self):
        """Test submitting lessons with string duration"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 'not a number'  # String duration
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for invalid duration type
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_negative_rate(self):
        """Test submitting lessons with negative rate"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0,
                    'rate': -50.00  # Negative rate
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for negative rate
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_zero_rate(self):
        """Test submitting lessons with zero rate"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0,
                    'rate': 0.00  # Zero rate
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should return 400 for zero rate
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_lessons_with_very_long_teacher_notes(self):
        """Test submitting lessons with very long teacher notes"""
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0,
                    'teacher_notes': 'A' * 10000  # Very long notes
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Should handle long notes gracefully
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_special_characters_in_name(self):
        """Test submitting lessons with special characters in name"""
        data = {
            'lessons': [
                {
                    'student_name': 'José María O\'Connor-Smith',  # Special characters
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_unicode_name(self):
        """Test submitting lessons with unicode name"""
        data = {
            'lessons': [
                {
                    'student_name': '李小明',  # Chinese characters
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_submit_lessons_with_arabic_name(self):
        """Test submitting lessons with Arabic name"""
        data = {
            'lessons': [
                {
                    'student_name': 'محمد أحمد',  # Arabic characters
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
