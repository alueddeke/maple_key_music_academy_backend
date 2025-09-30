# Maple Key Music Academy API - Swagger Documentation & Testing

## 🎯 Overview

This implementation provides comprehensive Swagger/OpenAPI documentation and contract testing for the Maple Key Music Academy API. It ensures that API behavior matches documentation and provides an interactive interface for development teams.

## 🚀 Features Implemented

### ✅ Swagger Documentation
- **Interactive API Explorer**: Full Swagger UI at `http://localhost:8000/api/docs/`
- **ReDoc Documentation**: Alternative documentation at `http://localhost:8000/api/redoc/`
- **OpenAPI Schema**: Machine-readable schema at `http://localhost:8000/api/schema/`
- **Authentication Integration**: JWT and OAuth authentication in Swagger UI
- **Comprehensive Examples**: Request/response examples for all endpoints

### ✅ Contract Testing
- **Schema Validation**: API responses match OpenAPI schemas
- **Business Logic Testing**: Workflows match documented behavior
- **Authentication Testing**: JWT and OAuth flows work as documented
- **Error Handling**: Error responses match documented formats
- **Performance Testing**: API meets documented performance expectations

### ✅ Docker Integration
- **Testing Service**: Isolated testing environment in Docker
- **Coverage Reports**: HTML and XML coverage reports
- **Test Reports**: Comprehensive test results and summaries
- **CI/CD Ready**: Automated testing pipeline integration

## 📋 API Documentation Structure

### Authentication Endpoints
- **JWT Token Authentication**: `/api/auth/token/`
- **Token Refresh**: `/api/auth/token/refresh/`
- **Google OAuth**: `/api/auth/google/`
- **User Profile**: `/api/auth/user/`
- **Logout**: `/api/auth/logout/`

### User Management
- **Teacher Directory**: `/api/billing/teachers/` (Public)
- **All Teachers**: `/api/billing/teachers/all/` (Management)
- **Teacher Approval**: `/api/billing/teachers/{id}/approve/` (Management)
- **Student Management**: `/api/billing/students/` (Students/Management)

### Lesson Management
- **Lesson List**: `/api/billing/lessons/` (Teachers/Management)
- **Request Lesson**: `/api/billing/lessons/request/` (Students)
- **Confirm Lesson**: `/api/billing/lessons/{id}/confirm/` (Teachers)
- **Complete Lesson**: `/api/billing/lessons/{id}/complete/` (Teachers)

### Invoice System
- **Teacher Invoices**: `/api/billing/invoices/teacher/` (Teachers/Management)
- **Submit Lessons**: `/api/billing/invoices/teacher/submit-lessons/` (Teachers)
- **Approve Invoice**: `/api/billing/invoices/teacher/{id}/approve/` (Management)

## 🔧 Setup Instructions

### 1. Install Dependencies
```bash
# Backend dependencies are already added to requirements.txt
pip install -r requirements.txt
```

### 2. Run Development Environment
```bash
# From the orchestrator directory
cd maple_key_music_academy_docker
docker-compose up --build
```

### 3. Access Swagger Documentation
- **Swagger UI**: http://localhost:8000/api/docs/
- **ReDoc**: http://localhost:8000/api/redoc/
- **OpenAPI Schema**: http://localhost:8000/api/schema/

### 4. Run Tests
```bash
# Run all Swagger and contract tests
python run_swagger_tests.py --coverage --html

# Run only contract tests
python run_swagger_tests.py --contract-only

# Run with performance testing
python run_swagger_tests.py --performance --verbose
```

## 🧪 Testing Framework

### Contract Testing
The implementation includes comprehensive contract testing that ensures:

1. **API Responses Match Schemas**: All responses conform to OpenAPI specifications
2. **Authentication Works**: JWT and OAuth flows function as documented
3. **Business Logic Compliance**: Workflows match documented behavior
4. **Error Handling**: Error responses follow documented formats
5. **Performance Standards**: API meets documented performance expectations

### Test Categories

#### Schema Validation Tests
- OpenAPI schema generation and validation
- Response structure compliance
- Request validation testing

#### Contract Tests
- API behavior matches documentation
- Authentication flow compliance
- Business logic workflow testing
- Error response format validation

#### Performance Tests
- Response time validation
- Authentication performance
- Database query optimization

### Test Data Factories
- **UserFactory**: Generate realistic user data
- **LessonFactory**: Create lesson scenarios
- **InvoiceFactory**: Generate billing scenarios
- **SwaggerExampleData**: Match Swagger documentation examples

## 🔐 Authentication in Swagger UI

### JWT Authentication
1. **Get Token**: Use `/api/auth/token/` endpoint
2. **Authorize**: Click "Authorize" button in Swagger UI
3. **Enter Token**: Paste access token in format `Bearer <token>`
4. **Test Endpoints**: All authenticated endpoints will work

### OAuth Authentication
1. **OAuth Flow**: Use `/api/auth/google/` for OAuth initiation
2. **Callback Handling**: Automatic token generation
3. **Token Usage**: Same as JWT authentication

## 📊 Business Logic Documentation

### Teacher Workflow
1. **Registration**: Teachers register via OAuth or management creation
2. **Approval**: Management approves teacher accounts
3. **Lesson Management**: Teachers schedule and complete lessons
4. **Invoice Submission**: Teachers submit completed lessons for payment
5. **Payment**: Management approves and processes payments

### Student Workflow
1. **Registration**: Students register via OAuth
2. **Teacher Selection**: Students browse approved teachers
3. **Lesson Requests**: Students request lessons from teachers
4. **Lesson Confirmation**: Teachers confirm lesson requests
5. **Lesson Completion**: Teachers mark lessons as completed

### Management Workflow
1. **User Management**: Approve teachers and students
2. **Invoice Approval**: Review and approve teacher invoices
3. **System Administration**: Manage all aspects of the music school

## 🐳 Docker Integration

### Development Environment
```yaml
# docker-compose.yaml includes:
services:
  api:          # Django backend with Swagger
  frontend:     # React frontend
  db:           # PostgreSQL database
  nginx:        # Reverse proxy with Swagger routes
  api-tests:    # Testing service (profile: testing)
```

### Testing Service
```bash
# Run tests in Docker
docker-compose --profile testing up api-tests

# View test reports
docker-compose exec api-tests ls -la test_reports/
```

### Nginx Configuration
- **Swagger Routes**: `/api/docs/`, `/api/redoc/`, `/api/schema/`
- **API Routes**: All `/api/*` endpoints
- **Frontend Routes**: Everything else routes to React

## 📈 Benefits for Development Team

### For Frontend Developers
- **Clear API Contracts**: Know exactly what data to send/receive
- **Interactive Testing**: Test endpoints directly in browser
- **Type Safety**: Generated TypeScript types from OpenAPI schema
- **Mock Services**: Generate mock APIs for development

### For Backend Developers
- **Documentation-First**: API behavior is clearly documented
- **Contract Testing**: Ensures implementation matches documentation
- **Schema Validation**: Automatic validation of request/response formats
- **Business Logic Clarity**: Complex workflows are clearly explained

### For QA/Testing
- **Comprehensive Test Coverage**: All endpoints and scenarios tested
- **Automated Validation**: Schema and contract testing
- **Performance Monitoring**: Response time validation
- **Error Scenario Testing**: All error cases documented and tested

### For Management
- **API Visibility**: Complete understanding of system capabilities
- **Business Logic Documentation**: Clear workflows and processes
- **Quality Assurance**: Automated testing ensures reliability
- **Development Efficiency**: Faster onboarding and development

## 🚀 Next Steps

### Immediate Actions
1. **Start Development Environment**: `docker-compose up --build`
2. **Access Swagger UI**: Visit http://localhost:8000/api/docs/
3. **Test Authentication**: Use the interactive authentication
4. **Explore Endpoints**: Test all documented endpoints

### Development Workflow
1. **API-First Development**: Define endpoints in Swagger first
2. **Contract Testing**: Ensure implementation matches documentation
3. **Schema Validation**: Validate all responses against schemas
4. **Continuous Testing**: Run tests in CI/CD pipeline

### Future Enhancements
- **API Versioning**: Support multiple API versions
- **Advanced Testing**: Property-based testing with schemathesis
- **Mock Services**: Generate mock APIs for frontend development
- **Performance Monitoring**: Real-time API performance tracking

## 📚 Resources

- **Swagger UI**: http://localhost:8000/api/docs/
- **ReDoc**: http://localhost:8000/api/redoc/
- **OpenAPI Schema**: http://localhost:8000/api/schema/
- **Test Reports**: `test_reports/` directory
- **Coverage Reports**: `test_reports/coverage_html/` directory

## 🎉 Success Metrics

✅ **Complete API Documentation**: All endpoints documented with examples
✅ **Interactive Testing Interface**: Swagger UI with authentication
✅ **Contract Testing**: API behavior matches documentation
✅ **Docker Integration**: Testing environment in containers
✅ **Business Logic Documentation**: Clear workflows and processes
✅ **Team Productivity**: Faster development and onboarding

The Maple Key Music Academy API now has comprehensive Swagger documentation and contract testing that will significantly improve development team productivity and API reliability.
