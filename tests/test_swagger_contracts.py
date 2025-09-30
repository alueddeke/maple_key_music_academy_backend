"""
Swagger Contract Testing for Maple Key Music Academy API

This module tests that the API behavior matches the OpenAPI/Swagger documentation.
It ensures that:
1. All endpoints return responses that match their schemas
2. Authentication flows work as documented
3. Business logic follows the documented workflows
4. Error responses match the documented formats
"""

import pytest
import json
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema
from .factories import UserFactory, LessonFactory, InvoiceFactory

User = get_user_model()


class SwaggerContractTests(APITestCase):
    """Test that API responses match OpenAPI schemas"""
    
    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        
        # Create test users
        self.management_user = UserFactory(
            user_type='management',
            is_approved=True,
            email='management@example.com'
        )
        self.teacher_user = UserFactory(
            user_type='teacher',
            is_approved=True,
            email='teacher@example.com'
        )
        self.student_user = UserFactory(
            user_type='student',
            is_approved=True,
            email='student@example.com'
        )
        
        # Create test data
        self.lesson = LessonFactory(teacher=self.teacher_user)
        self.invoice = InvoiceFactory(teacher=self.teacher_user)
    
    def test_teacher_list_get_schema_compliance(self):
        """Test that GET /api/billing/teachers/ returns schema-compliant response"""
        response = self.client.get('/api/billing/teachers/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Validate response structure matches UserSerializer schema
        data = response.json()
        self.assertIsInstance(data, list)
        
        if data:  # If there are teachers
            teacher = data[0]
            required_fields = ['id', 'email', 'first_name', 'last_name', 'user_type']
            for field in required_fields:
                self.assertIn(field, teacher)
    
    def test_teacher_list_post_schema_compliance(self):
        """Test that POST /api/billing/teachers/ follows schema requirements"""
        # Authenticate as management
        token = RefreshToken.for_user(self.management_user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        
        teacher_data = {
            'email': 'new.teacher@example.com',
            'first_name': 'New',
            'last_name': 'Teacher',
            'password': 'securepassword123',
            'bio': 'Test teacher bio',
            'instruments': 'Piano',
            'hourly_rate': '70.00',
            'phone_number': '555-0123',
            'address': '123 Test St'
        }
        
        response = self.client.post('/api/billing/teachers/', teacher_data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Validate response matches UserSerializer schema
        data = response.json()
        required_fields = ['id', 'email', 'first_name', 'last_name', 'user_type', 'is_approved']
        for field in required_fields:
            self.assertIn(field, data)
        
        # Validate business logic
        self.assertTrue(data['is_approved'])  # Management-created teachers are auto-approved
        self.assertEqual(data['user_type'], 'teacher')
    
    def test_authentication_schema_compliance(self):
        """Test that JWT authentication follows documented schema"""
        # Test successful authentication
        auth_data = {
            'email': self.teacher_user.email,
            'password': 'password123'  # Default password from factory
        }
        
        response = self.client.post('/api/auth/token/', auth_data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Validate response schema
        data = response.json()
        required_fields = ['access_token', 'refresh_token', 'user']
        for field in required_fields:
            self.assertIn(field, data)
        
        # Validate user object schema
        user_data = data['user']
        user_required_fields = ['email', 'name', 'user_id', 'user_type', 'is_approved']
        for field in user_required_fields:
            self.assertIn(field, user_data)
    
    def test_lesson_submission_schema_compliance(self):
        """Test that lesson submission follows documented schema"""
        # Authenticate as teacher
        token = RefreshToken.for_user(self.teacher_user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        
        lesson_data = {
            'month': 'January 2024',
            'lessons': [
                {
                    'student_name': 'Test Student',
                    'student_email': 'student@example.com',
                    'scheduled_date': '2024-01-15T14:00:00Z',
                    'duration': 1.0,
                    'rate': 65.00,
                    'teacher_notes': 'Test lesson notes'
                }
            ]
        }
        
        response = self.client.post('/api/billing/invoices/teacher/submit-lessons/', 
                                  lesson_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Validate response schema
        data = response.json()
        required_fields = ['message', 'invoice', 'lessons_created']
        for field in required_fields:
            self.assertIn(field, data)
        
        # Validate invoice schema
        invoice_data = data['invoice']
        invoice_required_fields = ['id', 'invoice_type', 'status', 'payment_balance', 'teacher']
        for field in invoice_required_fields:
            self.assertIn(field, invoice_data)
    
    def test_error_response_schema_compliance(self):
        """Test that error responses follow documented schema"""
        # Test 401 Unauthorized
        response = self.client.get('/api/billing/teachers/all/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        
        # Test 403 Forbidden
        token = RefreshToken.for_user(self.student_user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        
        response = self.client.get('/api/billing/teachers/all/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Validate error response schema
        data = response.json()
        self.assertIn('error', data)
    
    def test_business_logic_workflow_compliance(self):
        """Test that business logic follows documented workflows"""
        # Test teacher approval workflow
        token = RefreshToken.for_user(self.management_user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        
        # Create unapproved teacher
        unapproved_teacher = UserFactory(
            user_type='teacher',
            is_approved=False,
            email='unapproved@example.com'
        )
        
        # Approve teacher
        response = self.client.post(f'/api/billing/teachers/{unapproved_teacher.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify teacher is now approved
        unapproved_teacher.refresh_from_db()
        self.assertTrue(unapproved_teacher.is_approved)
    
    def test_oauth_flow_schema_compliance(self):
        """Test that OAuth flow follows documented schema"""
        # Test OAuth initiation
        response = self.client.get('/api/auth/google/')
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        
        # Verify redirect to Google OAuth
        self.assertTrue('accounts.google.com' in response.url)


class SchemaValidationTests(TestCase):
    """Test OpenAPI schema validation"""
    
    def test_openapi_schema_generation(self):
        """Test that OpenAPI schema can be generated without errors"""
        from drf_spectacular.openapi import AutoSchema
        from django.urls import reverse
        
        # Test that schema endpoint is accessible
        client = Client()
        response = client.get('/api/schema/')
        self.assertEqual(response.status_code, 200)
        
        # Validate schema is valid JSON
        schema = response.json()
        self.assertIn('openapi', schema)
        self.assertIn('info', schema)
        self.assertIn('paths', schema)
    
    def test_swagger_ui_accessibility(self):
        """Test that Swagger UI is accessible"""
        client = Client()
        response = client.get('/api/docs/')
        self.assertEqual(response.status_code, 200)
        
        # Verify it's HTML content
        self.assertIn('text/html', response['Content-Type'])
    
    def test_redoc_accessibility(self):
        """Test that ReDoc is accessible"""
        client = Client()
        response = client.get('/api/redoc/')
        self.assertEqual(response.status_code, 200)
        
        # Verify it's HTML content
        self.assertIn('text/html', response['Content-Type'])


class ContractTestingTests(APITestCase):
    """Advanced contract testing using OpenAPI schemas"""
    
    def setUp(self):
        self.client = APIClient()
        self.teacher_user = UserFactory(
            user_type='teacher',
            is_approved=True,
            email='contract.test@example.com'
        )
    
    def test_api_contract_consistency(self):
        """Test that API behavior is consistent with OpenAPI contract"""
        # Get the OpenAPI schema
        response = self.client.get('/api/schema/')
        schema = response.json()
        
        # Test that all documented endpoints exist
        paths = schema.get('paths', {})
        
        # Key endpoints that should be documented
        expected_endpoints = [
            '/api/billing/teachers/',
            '/api/billing/lessons/',
            '/api/billing/invoices/teacher/',
            '/api/auth/token/',
            '/api/auth/google/'
        ]
        
        for endpoint in expected_endpoints:
            # Check if endpoint is documented
            self.assertIn(endpoint, paths, f"Endpoint {endpoint} not found in OpenAPI schema")
    
    def test_response_schema_validation(self):
        """Test that actual responses match OpenAPI response schemas"""
        # Test teacher list endpoint
        response = self.client.get('/api/billing/teachers/')
        
        # Basic schema validation
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        
        # Test authentication endpoint
        auth_data = {
            'email': self.teacher_user.email,
            'password': 'password123'
        }
        response = self.client.post('/api/auth/token/', auth_data)
        
        if response.status_code == 200:
            data = response.json()
            # Validate JWT response schema
            self.assertIn('access_token', data)
            self.assertIn('refresh_token', data)
            self.assertIn('user', data)
            
            # Validate user object
            user_data = data['user']
            self.assertIn('email', user_data)
            self.assertIn('user_type', user_data)


class PerformanceContractTests(APITestCase):
    """Test that API performance meets documented expectations"""
    
    def setUp(self):
        self.client = APIClient()
        self.teacher_user = UserFactory(
            user_type='teacher',
            is_approved=True
        )
    
    def test_response_time_contracts(self):
        """Test that API responses meet performance expectations"""
        import time
        
        # Test teacher list performance
        start_time = time.time()
        response = self.client.get('/api/billing/teachers/')
        end_time = time.time()
        
        self.assertEqual(response.status_code, 200)
        # Response should be fast (under 1 second for simple queries)
        self.assertLess(end_time - start_time, 1.0)
    
    def test_authentication_performance(self):
        """Test that authentication is performant"""
        import time
        
        auth_data = {
            'email': self.teacher_user.email,
            'password': 'password123'
        }
        
        start_time = time.time()
        response = self.client.post('/api/auth/token/', auth_data)
        end_time = time.time()
        
        # Authentication should be fast
        self.assertLess(end_time - start_time, 2.0)


# Pytest fixtures for contract testing
@pytest.fixture
def api_client():
    """Fixture for API client with authentication"""
    return APIClient()


@pytest.fixture
def authenticated_teacher(api_client):
    """Fixture for authenticated teacher user"""
    teacher = UserFactory(user_type='teacher', is_approved=True)
    token = RefreshToken.for_user(teacher)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return teacher, api_client


@pytest.fixture
def authenticated_management(api_client):
    """Fixture for authenticated management user"""
    management = UserFactory(user_type='management', is_approved=True)
    token = RefreshToken.for_user(management)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return management, api_client


# Pytest-based contract tests
@pytest.mark.django_db
def test_teacher_creation_contract(authenticated_management):
    """Test teacher creation follows contract"""
    management, client = authenticated_management
    
    teacher_data = {
        'email': 'contract.teacher@example.com',
        'first_name': 'Contract',
        'last_name': 'Teacher',
        'password': 'securepassword123',
        'bio': 'Contract test teacher',
        'instruments': 'Piano',
        'hourly_rate': '75.00'
    }
    
    response = client.post('/api/billing/teachers/', teacher_data)
    
    assert response.status_code == 201
    data = response.json()
    
    # Validate contract compliance
    assert 'id' in data
    assert data['user_type'] == 'teacher'
    assert data['is_approved'] is True  # Management-created teachers are auto-approved


@pytest.mark.django_db
def test_lesson_submission_contract(authenticated_teacher):
    """Test lesson submission follows contract"""
    teacher, client = authenticated_teacher
    
    lesson_data = {
        'month': 'Contract Test Month',
        'lessons': [
            {
                'student_name': 'Contract Student',
                'scheduled_date': '2024-01-15T14:00:00Z',
                'duration': 1.0,
                'rate': 65.00,
                'teacher_notes': 'Contract test lesson'
            }
        ]
    }
    
    response = client.post('/api/billing/invoices/teacher/submit-lessons/', 
                          lesson_data, format='json')
    
    assert response.status_code == 201
    data = response.json()
    
    # Validate contract compliance
    assert 'message' in data
    assert 'invoice' in data
    assert 'lessons_created' in data
    assert data['lessons_created'] == 1


@pytest.mark.django_db
def test_authentication_contract(api_client):
    """Test authentication follows contract"""
    teacher = UserFactory(user_type='teacher', is_approved=True)
    
    auth_data = {
        'email': teacher.email,
        'password': 'password123'
    }
    
    response = api_client.post('/api/auth/token/', auth_data)
    
    assert response.status_code == 200
    data = response.json()
    
    # Validate contract compliance
    assert 'access_token' in data
    assert 'refresh_token' in data
    assert 'user' in data
    
    user_data = data['user']
    assert 'email' in user_data
    assert 'user_type' in user_data
    assert 'is_approved' in user_data
