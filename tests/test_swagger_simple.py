"""
Simple Swagger Tests for Maple Key Music Academy API

This module tests basic Swagger functionality without complex dependencies.
"""

import os
import django
from django.test import TestCase, Client
from django.urls import reverse


class SwaggerBasicTests(TestCase):
    """Test basic Swagger functionality"""
    
    def setUp(self):
        """Set up test client"""
        self.client = Client()
    
    def test_swagger_ui_accessible(self):
        """Test that Swagger UI is accessible"""
        response = self.client.get('/api/docs/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response['Content-Type'])
        self.assertIn('swagger', response.content.decode().lower())
    
    def test_redoc_accessible(self):
        """Test that ReDoc is accessible"""
        response = self.client.get('/api/redoc/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response['Content-Type'])
        self.assertIn('redoc', response.content.decode().lower())
    
    def test_openapi_schema_accessible(self):
        """Test that OpenAPI schema is accessible"""
        response = self.client.get('/api/schema/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/json', response['Content-Type'])
        
        # Validate schema structure
        schema = response.json()
        self.assertIn('openapi', schema)
        self.assertIn('info', schema)
        self.assertIn('paths', schema)
        self.assertIn('components', schema)
    
    def test_schema_has_required_info(self):
        """Test that schema has required information"""
        response = self.client.get('/api/schema/')
        schema = response.json()
        
        # Check info section
        info = schema.get('info', {})
        self.assertIn('title', info)
        self.assertIn('version', info)
        self.assertIn('description', info)
        
        # Check that it's our API
        self.assertIn('Maple Key', info.get('title', ''))
    
    def test_schema_has_api_paths(self):
        """Test that schema includes our API paths"""
        response = self.client.get('/api/schema/')
        schema = response.json()
        paths = schema.get('paths', {})
        
        # Check for key API endpoints
        expected_endpoints = [
            '/api/billing/teachers/',
            '/api/auth/token/',
            '/api/auth/google/',
        ]
        
        for endpoint in expected_endpoints:
            self.assertIn(endpoint, paths, f"Endpoint {endpoint} not found in schema")
    
    def test_schema_has_authentication(self):
        """Test that schema includes authentication components"""
        response = self.client.get('/api/schema/')
        schema = response.json()
        
        components = schema.get('components', {})
        security_schemes = components.get('securitySchemes', {})
        
        # Check for JWT authentication
        self.assertIn('Bearer', security_schemes)
        jwt_auth = security_schemes.get('Bearer', {})
        self.assertEqual(jwt_auth.get('type'), 'http')
        self.assertEqual(jwt_auth.get('scheme'), 'bearer')
    
    def test_schema_has_tags(self):
        """Test that schema includes organized tags"""
        response = self.client.get('/api/schema/')
        schema = response.json()
        
        # Check for tags
        self.assertIn('tags', schema)
        tags = schema.get('tags', [])
        
        # Check for expected tags
        tag_names = [tag.get('name') for tag in tags]
        expected_tags = ['Authentication', 'Users', 'Lessons', 'Invoices']
        
        for expected_tag in expected_tags:
            self.assertIn(expected_tag, tag_names, f"Tag {expected_tag} not found")


class SwaggerEndpointTests(TestCase):
    """Test that Swagger endpoints work correctly"""
    
    def setUp(self):
        """Set up test client"""
        self.client = Client()
    
    def test_teachers_endpoint_documented(self):
        """Test that teachers endpoint is properly documented"""
        response = self.client.get('/api/schema/')
        schema = response.json()
        paths = schema.get('paths', {})
        
        teachers_path = paths.get('/api/billing/teachers/', {})
        self.assertIn('get', teachers_path)
        self.assertIn('post', teachers_path)
        
        # Check GET operation
        get_op = teachers_path.get('get', {})
        self.assertIn('summary', get_op)
        self.assertIn('description', get_op)
        self.assertIn('tags', get_op)
        
        # Check POST operation
        post_op = teachers_path.get('post', {})
        self.assertIn('summary', post_op)
        self.assertIn('description', post_op)
        self.assertIn('tags', post_op)
    
    def test_auth_endpoint_documented(self):
        """Test that authentication endpoint is properly documented"""
        response = self.client.get('/api/schema/')
        schema = response.json()
        paths = schema.get('paths', {})
        
        auth_path = paths.get('/api/auth/token/', {})
        self.assertIn('post', auth_path)
        
        post_op = auth_path.get('post', {})
        self.assertIn('summary', post_op)
        self.assertIn('description', post_op)
        self.assertIn('requestBody', post_op)
        self.assertIn('responses', post_op)
    
    def test_schema_has_examples(self):
        """Test that schema includes examples"""
        response = self.client.get('/api/schema/')
        schema = response.json()
        
        # Check for examples in paths
        paths = schema.get('paths', {})
        
        # Look for examples in any endpoint
        has_examples = False
        for path, methods in paths.items():
            for method, operation in methods.items():
                if isinstance(operation, dict) and 'examples' in operation:
                    has_examples = True
                    break
            if has_examples:
                break
        
        # We should have examples in our documented endpoints
        self.assertTrue(has_examples, "No examples found in schema")


class SwaggerIntegrationTests(TestCase):
    """Test Swagger integration with the actual API"""
    
    def setUp(self):
        """Set up test client"""
        self.client = Client()
    
    def test_swagger_ui_serves_static_files(self):
        """Test that Swagger UI can serve static files"""
        response = self.client.get('/api/docs/')
        self.assertEqual(response.status_code, 200)
        
        # Check that it's actually serving Swagger UI
        content = response.content.decode()
        self.assertIn('swagger', content.lower())
        self.assertIn('api', content.lower())
    
    def test_redoc_serves_correctly(self):
        """Test that ReDoc serves correctly"""
        response = self.client.get('/api/redoc/')
        self.assertEqual(response.status_code, 200)
        
        # Check that it's actually serving ReDoc
        content = response.content.decode()
        self.assertIn('redoc', content.lower())
    
    def test_schema_endpoint_returns_valid_json(self):
        """Test that schema endpoint returns valid JSON"""
        response = self.client.get('/api/schema/')
        self.assertEqual(response.status_code, 200)
        
        # Try to parse as JSON (should not raise exception)
        import json
        schema = json.loads(response.content.decode())
        self.assertIsInstance(schema, dict)
    
    def test_schema_has_servers_configuration(self):
        """Test that schema includes server configuration"""
        response = self.client.get('/api/schema/')
        schema = response.json()
        
        # Check for servers configuration
        self.assertIn('servers', schema)
        servers = schema.get('servers', [])
        self.assertGreater(len(servers), 0)
        
        # Check server URL
        server = servers[0]
        self.assertIn('url', server)
        self.assertIn('localhost', server.get('url', ''))
