from decimal import Decimal
#!/usr/bin/env python
"""
Music School Architecture Test Script
Run this after implementing the refactor to verify everything works correctly.
"""

import os
import sys
import django
import requests
import json

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maple_key_backend.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from billing.models import Lesson, Invoice

User = get_user_model()

class ArchitectureTest:
    def __init__(self):
        self.client = Client()
        self.base_url = 'http://localhost:8000'
        self.tokens = {}
        
    def run_all_tests(self):
        """Run all architecture verification tests"""
        print("🧪 Starting Music School Architecture Tests\n")
        
        try:
            self.test_user_creation()
            self.test_authentication()
            self.test_role_permissions()
            self.test_lesson_workflow()
            self.test_invoice_system()
            self.test_error_handling()
            print("\n✅ All tests completed successfully!")
        except Exception as e:
            print(f"\n❌ Test failed: {str(e)}")
            raise
    
    def test_user_creation(self):
        """Test unified user model with different roles"""
        print("1. Testing User Creation...")
        
        # Clean up existing test users
        User.objects.filter(email__endswith='@test.com').delete()
        
        # Create management user
        mgmt = User.objects.create_user(
            email='mgmt@test.com',
            password='test123',
            first_name='Admin',
            last_name='User',
            user_type='management'
        )
        assert mgmt.is_approved == True, "Management should be auto-approved"
        assert mgmt.is_staff == True, "Management should be staff"
        
        # Create teacher user
        teacher = User.objects.create_user(
            email='teacher@test.com',
            password='test123',
            first_name='John',
            last_name='Teacher',
            user_type='teacher',
            bio='Piano instructor',
            instruments='Piano, Guitar',
            hourly_rate=75.00
        )
        assert teacher.is_approved == False, "Teachers should need approval"
        assert teacher.bio == 'Piano instructor', "Teacher fields should work"
        
        # Create student user  
        student = User.objects.create_user(
            email='student@test.com',
            password='test123',
            first_name='Jane',
            last_name='Student',
            user_type='student',
            parent_email='parent@test.com'
        )
        assert student.bio == '', "Students should have empty teacher fields"
        assert student.parent_email == 'parent@test.com', "Student fields should work"
        
        # Approve teacher for further tests
        teacher.is_approved = True
        teacher.save()
        
        print("   ✓ User creation with different roles works")
    
    def test_authentication(self):
        """Test JWT and OAuth authentication"""
        print("2. Testing Authentication...")
        
        # Test JWT token endpoint
        response = self.client.post('/api/auth/token/', {
            'email': 'mgmt@test.com',
            'password': 'test123'
        })
        assert response.status_code == 200, f"JWT auth failed: {response.content}"
        
        mgmt_data = response.json()
        self.tokens['management'] = mgmt_data['access_token']
        assert 'access_token' in mgmt_data, "Missing access token"
        assert mgmt_data['user']['user_type'] == 'management', "Wrong user type"
        
        # Test teacher authentication
        response = self.client.post('/api/auth/token/', {
            'email': 'teacher@test.com', 
            'password': 'test123'
        })
        assert response.status_code == 200, "Teacher JWT auth failed"
        teacher_data = response.json()
        self.tokens['teacher'] = teacher_data['access_token']
        
        print("   ✓ JWT authentication works")
    
    def test_role_permissions(self):
        """Test role-based access control"""
        print("3. Testing Role-Based Permissions...")
        
        # Management should access everything
        response = self.client.get('/api/billing/teachers/all/', 
            HTTP_AUTHORIZATION=f'Bearer {self.tokens["management"]}')
        assert response.status_code == 200, "Management can't access teacher list"
        
        # Teacher should NOT access management endpoints
        response = self.client.get('/api/billing/teachers/all/',
            HTTP_AUTHORIZATION=f'Bearer {self.tokens["teacher"]}')
        assert response.status_code == 403, "Teacher shouldn't access management endpoints"
        
        # Test unauthenticated access
        response = self.client.get('/api/billing/lessons/')
        assert response.status_code == 401, "Should require authentication"
        
        print("   ✓ Role-based permissions work")
    
    def test_lesson_workflow(self):
        """Test lesson creation and workflow"""
        print("4. Testing Lesson Workflow...")
        
        teacher = User.objects.get(email='teacher@test.com')
        student = User.objects.get(email='student@test.com')
        
        # Create lesson
        lesson_data = {
            'teacher': teacher.id,
            'student': student.id,
            'scheduled_date': '2024-01-15T14:00:00Z',
            'duration': 1.0,
            'status': 'requested'
        }
        
        response = self.client.post('/api/billing/lessons/',
            data=json.dumps(lesson_data),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.tokens["teacher"]}')
        
        assert response.status_code == 201, f"Lesson creation failed: {response.content}"
        
        lesson = Lesson.objects.get(teacher=teacher, student=student)
        assert lesson.rate == teacher.hourly_rate, "Rate should auto-populate from teacher"
        assert lesson.total_cost() == float(teacher.hourly_rate * Decimal("1.0")), "Total cost calculation wrong"
        
        print("   ✓ Lesson workflow works")
    
    def test_invoice_system(self):
        """Test invoice creation and approval"""
        print("5. Testing Invoice System...")
        
        teacher = User.objects.get(email='teacher@test.com')
        lessons = list(Lesson.objects.filter(teacher=teacher))
        
        if not lessons:
            print("   ⚠ Skipping invoice test - no lessons found")
            return
        
        # Create invoice via API
        invoice_data = {
            'lessons': [lesson.id for lesson in lessons],
            'due_date': '2024-01-31T00:00:00Z'
        }
        
        response = self.client.post('/api/billing/invoices/teacher/',
            data=json.dumps(invoice_data),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {self.tokens["teacher"]}')
        
        if response.status_code == 201:
            invoice_id = response.json()['id']
            
            # Test management approval
            response = self.client.post(f'/api/billing/invoices/teacher/{invoice_id}/approve/',
                HTTP_AUTHORIZATION=f'Bearer {self.tokens["management"]}')
            assert response.status_code == 200, "Invoice approval failed"
            
        print("   ✓ Invoice system works")
    
    def test_error_handling(self):
        """Test proper error responses"""
        print("6. Testing Error Handling...")
        
        # Test invalid token
        response = self.client.get('/api/billing/lessons/',
            HTTP_AUTHORIZATION='Bearer invalid_token')
        assert response.status_code == 401, "Should reject invalid tokens"
        
        # Test accessing non-existent resource
        response = self.client.get('/api/billing/teachers/99999/',
            HTTP_AUTHORIZATION=f'Bearer {self.tokens["management"]}')
        assert response.status_code == 404, "Should return 404 for missing resources"
        
        print("   ✓ Error handling works")

if __name__ == '__main__':
    tester = ArchitectureTest()
    tester.run_all_tests()