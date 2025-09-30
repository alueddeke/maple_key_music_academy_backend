# Maple Key Music Academy - Comprehensive Testing Guide

This guide covers all testing approaches for the Maple Key Music Academy API, including unit tests, integration tests, Swagger contract testing, and API documentation validation.

## Table of Contents
1. [Quick Start](#quick-start)
2. [Testing Environment Setup](#testing-environment-setup)
3. [Running Tests](#running-tests)
4. [Test Categories](#test-categories)
5. [Swagger Documentation Testing](#swagger-documentation-testing)
6. [API Testing Workflows](#api-testing-workflows)
7. [Coverage Reports](#coverage-reports)
8. [Docker Testing Commands](#docker-testing-commands)
9. [CI/CD Integration](#cicd-integration)
10. [Troubleshooting](#troubleshooting)

## Quick Start

### Prerequisites
- Docker and Docker Compose installed
- Access to the orchestrator repository (`maple_key_music_academy_docker`)

### Run All Tests
```bash
# From the orchestrator directory
cd maple_key_music_academy_docker
docker-compose --profile testing up api-tests
```

### Access Swagger Documentation
```bash
# Start development environment
docker-compose up --build

# Access documentation
# Swagger UI: http://localhost:8000/api/docs/
# ReDoc: http://localhost:8000/api/redoc/
# OpenAPI Schema: http://localhost:8000/api/schema/
```

## Testing Environment Setup

### Docker Testing Service
The testing environment is configured in `docker-compose.yaml`:

```yaml
api-tests:
  build:
    context: ../maple_key_music_academy_backend
    dockerfile: Dockerfile
  container_name: maple_key_api_tests
  env_file:
    - ./.envs/env.dev
  depends_on:
    db:
      condition: service_healthy
  volumes:
    - ../maple_key_music_academy_backend:/usr/app/
    - test_reports:/usr/app/test_reports/
  command: |
    bash -c "
    python3 manage.py migrate --no-input &&
    python3 manage.py collectstatic --noinput &&
    pytest --cov=. --cov-report=html --cov-report=term --junitxml=test_reports/junit.xml --html=test_reports/report.html --self-contained-html
    "
  profiles:
    - testing
```

### Test Directory Structure
```
maple_key_music_academy_backend/
├── tests/
│   ├── test_swagger_basic.py          # Swagger functionality tests
│   ├── test_swagger_contracts.py      # Contract testing (advanced)
│   ├── test_swagger_simple.py         # Simple Swagger tests
│   └── factories.py                    # Test data factories
├── testing/
│   ├── swagger/
│   │   ├── run_swagger_tests.py       # Swagger test runner
│   │   └── SWAGGER_IMPLEMENTATION.md  # Swagger documentation
│   ├── coverage/                       # Coverage reports
│   └── pytest.ini                     # pytest configuration
└── billing/
    └── test_services.py               # Service-specific tests
```

## Running Tests

### 1. Full Test Suite with Coverage
```bash
# Run all tests with comprehensive reporting
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=html --cov-report=term --junitxml=test_reports/junit.xml --html=test_reports/report.html --self-contained-html

# Run with verbose output
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=html --cov-report=term -v
```

### 2. Specific Test Categories
```bash
# Run only unit tests
docker-compose --profile testing run --rm api-tests pytest tests/ -k "not integration"

# Run only integration tests
docker-compose --profile testing run --rm api-tests pytest tests/ -k "integration"

# Run only Swagger tests
docker-compose --profile testing run --rm api-tests pytest tests/test_swagger_basic.py -v

# Run Swagger contract tests
docker-compose --profile testing run --rm api-tests pytest tests/test_swagger_contracts.py -v
```

### 3. Django Test Runner
```bash
# Use Django's built-in test runner
docker-compose --profile testing run --rm api-tests python manage.py test --verbosity=2

# Run specific test modules
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic --verbosity=2

# Run specific test classes
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic.SwaggerBasicTests --verbosity=2
```

### 4. Individual Test Files
```bash
# Run specific test files
docker-compose --profile testing run --rm api-tests pytest tests/test_swagger_basic.py::SwaggerBasicTests::test_swagger_ui_accessible -v

# Run with debug output
docker-compose --profile testing run --rm api-tests pytest tests/test_swagger_basic.py -v -s --tb=long
```

## Test Categories

### 1. Unit Tests
- **Location**: `tests/` directory
- **Purpose**: Test individual components in isolation
- **Coverage**: Models, serializers, services, utilities
- **Command**: `pytest tests/ -k "not integration"`

### 2. Integration Tests
- **Location**: `tests/` directory (marked with `@pytest.mark.integration`)
- **Purpose**: Test component interactions
- **Coverage**: API endpoints, database operations, external services
- **Command**: `pytest tests/ -k "integration"`

### 3. Swagger Contract Tests
- **Location**: `tests/test_swagger_basic.py`, `tests/test_swagger_contracts.py`
- **Purpose**: Validate API documentation and schema compliance
- **Coverage**: OpenAPI schema generation, endpoint documentation, authentication flows
- **Command**: `pytest tests/test_swagger_basic.py -v`

### 4. Service Tests
- **Location**: `billing/test_services.py`
- **Purpose**: Test business logic services
- **Coverage**: Invoice processing, email services, PDF generation
- **Command**: `pytest billing/test_services.py -v`

### 5. API Endpoint Tests
- **Location**: `tests/` directory
- **Purpose**: Test API endpoints and business logic
- **Coverage**: Authentication, CRUD operations, business workflows
- **Command**: `pytest tests/ -k "api"`

## Swagger Documentation Testing

### Access Swagger Documentation
1. **Start Development Environment**:
   ```bash
   cd maple_key_music_academy_docker
   docker-compose up --build
   ```

2. **Access Documentation**:
   - **Swagger UI**: http://localhost:8000/api/docs/
   - **ReDoc**: http://localhost:8000/api/redoc/
   - **OpenAPI Schema**: http://localhost:8000/api/schema/

### Test Swagger Functionality
```bash
# Test basic Swagger functionality
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic --verbosity=2

# Test Swagger UI accessibility
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic.SwaggerBasicTests.test_swagger_ui_accessible --verbosity=2

# Test OpenAPI schema generation
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic.SwaggerBasicTests.test_openapi_schema_accessible --verbosity=2
```

### Interactive Testing
1. **Authentication Testing**:
   - Use `/api/auth/token/` endpoint in Swagger UI
   - Test JWT token generation and validation
   - Test OAuth flow with `/api/auth/google/`

2. **Endpoint Testing**:
   - Test all documented endpoints
   - Verify request/response schemas
   - Test error handling scenarios

3. **Business Logic Testing**:
   - Test teacher approval workflows
   - Test lesson submission and invoice creation
   - Test management approval processes

## API Testing Workflows

### 1. Authentication Flow Testing
```bash
# Test JWT authentication
curl -X POST http://localhost:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "password123"}'

# Test OAuth initiation
curl http://localhost:8000/api/auth/google/
```

### 2. Teacher Management Testing
```bash
# Test teacher list (public)
curl http://localhost:8000/api/billing/teachers/

# Test teacher creation (requires management auth)
curl -X POST http://localhost:8000/api/billing/teachers/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"email": "teacher@example.com", "first_name": "John", "last_name": "Doe", "password": "password123"}'
```

### 3. Lesson Management Testing
```bash
# Test lesson submission (requires teacher auth)
curl -X POST http://localhost:8000/api/billing/invoices/teacher/submit-lessons/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "month": "January 2024",
    "lessons": [
      {
        "student_name": "John Smith",
        "scheduled_date": "2024-01-15T14:00:00Z",
        "duration": 1.0,
        "rate": 65.00,
        "teacher_notes": "Great lesson on scales"
      }
    ]
  }'
```

### 4. Invoice Management Testing
```bash
# Test invoice approval (requires management auth)
curl -X POST http://localhost:8000/api/billing/invoices/teacher/1/approve/ \
  -H "Authorization: Bearer <token>"
```

## Coverage Reports

### Generate Coverage Reports
```bash
# Run tests with coverage
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=html --cov-report=term

# Run with specific coverage targets
docker-compose --profile testing run --rm api-tests pytest --cov=billing --cov=custom_auth --cov-report=html --cov-report=term

# View coverage report
docker-compose --profile testing run --rm api-tests ls -la test_reports/
```

### Coverage Report Locations
- **HTML Report**: `test_reports/coverage_html/index.html`
- **Terminal Report**: Displayed in console output
- **XML Report**: `test_reports/coverage.xml` (for CI/CD)
- **JUnit Report**: `test_reports/junit.xml`

### Coverage Goals
- **Overall Coverage**: >80%
- **Critical Business Logic**: >90%
- **API Endpoints**: >85%
- **Authentication**: >95%

## Docker Testing Commands

### Basic Testing Commands
```bash
# Run all tests
docker-compose --profile testing run --rm api-tests pytest

# Run with coverage
docker-compose --profile testing run --rm api-tests pytest --cov=.

# Run specific tests
docker-compose --profile testing run --rm api-tests pytest tests/test_swagger_basic.py

# Run with verbose output
docker-compose --profile testing run --rm api-tests pytest -v

# Run with debug output
docker-compose --profile testing run --rm api-tests pytest -v -s --tb=long
```

### Django Test Commands
```bash
# Run Django tests
docker-compose --profile testing run --rm api-tests python manage.py test

# Run specific Django tests
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic

# Run with verbosity
docker-compose --profile testing run --rm api-tests python manage.py test --verbosity=2
```

### Swagger Testing Commands
```bash
# Test Swagger functionality
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic --verbosity=2

# Test Swagger UI
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic.SwaggerBasicTests.test_swagger_ui_accessible --verbosity=2

# Test OpenAPI schema
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic.SwaggerBasicTests.test_openapi_schema_accessible --verbosity=2
```

### Service Testing Commands
```bash
# Test billing services
docker-compose --profile testing run --rm api-tests pytest billing/test_services.py -v

# Test with coverage
docker-compose --profile testing run --rm api-tests pytest billing/test_services.py --cov=billing --cov-report=html
```

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Test Suite
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run Tests
        run: |
          cd maple_key_music_academy_docker
          docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=xml
      - name: Upload Coverage
        uses: codecov/codecov-action@v1
        with:
          file: test_reports/coverage.xml
```

### Test Reports
- **JUnit XML**: `test_reports/junit.xml`
- **HTML Report**: `test_reports/report.html`
- **Coverage XML**: `test_reports/coverage.xml`

### Continuous Integration Commands
```bash
# Run tests in CI
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=xml --junitxml=test_reports/junit.xml

# Run with specific coverage thresholds
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-fail-under=80
```

## Troubleshooting

### Common Issues

#### 1. Database Connection Issues
```bash
# Check database health
docker-compose logs db

# Restart database
docker-compose restart db

# Check database connectivity
docker-compose exec db psql -U maple_key_user -d maple_key_dev -c "SELECT 1;"
```

#### 2. Test Environment Issues
```bash
# Rebuild test container
docker-compose --profile testing build api-tests

# Run with fresh database
docker-compose --profile testing run --rm api-tests python manage.py migrate --run-syncdb

# Clear test database
docker-compose --profile testing run --rm api-tests python manage.py flush --noinput
```

#### 3. Coverage Issues
```bash
# Clear coverage data
docker-compose --profile testing run --rm api-tests coverage erase

# Run with fresh coverage
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=html

# Check coverage files
docker-compose --profile testing run --rm api-tests ls -la test_reports/
```

#### 4. Swagger Issues
```bash
# Test Swagger endpoints directly
curl http://localhost:8000/api/schema/
curl http://localhost:8000/api/docs/
curl http://localhost:8000/api/redoc/

# Check Swagger configuration
docker-compose --profile testing run --rm api-tests python manage.py shell -c "from drf_spectacular.utils import extend_schema; print('Swagger configured')"
```

### Debug Mode
```bash
# Run tests with debug output
docker-compose --profile testing run --rm api-tests pytest -v -s --tb=long

# Run specific test with debug
docker-compose --profile testing run --rm api-tests pytest tests/test_swagger_basic.py::SwaggerBasicTests::test_swagger_ui_accessible -v -s --tb=long

# Run with maximum verbosity
docker-compose --profile testing run --rm api-tests pytest -vvv -s --tb=long
```

### Performance Testing
```bash
# Run tests with timing
docker-compose --profile testing run --rm api-tests pytest --durations=10

# Run with performance profiling
docker-compose --profile testing run --rm api-tests pytest --profile --profile-svg
```

## Best Practices

### 1. Test Organization
- Keep tests close to the code they test
- Use descriptive test names
- Group related tests in classes
- Use factories for test data generation

### 2. Test Data
- Use factories for test data generation
- Clean up test data after each test
- Use database transactions for isolation
- Mock external services

### 3. Coverage Goals
- Aim for >80% code coverage
- Focus on critical business logic
- Test error scenarios and edge cases
- Test authentication and authorization

### 4. Performance
- Keep tests fast (< 1 second per test)
- Use database transactions for isolation
- Mock external services
- Use parallel test execution when possible

### 5. Documentation
- Document complex test scenarios
- Keep test documentation up to date
- Use meaningful test descriptions
- Document test data requirements

## Additional Resources

- **Django Testing**: https://docs.djangoproject.com/en/stable/topics/testing/
- **pytest Documentation**: https://docs.pytest.org/
- **Coverage.py**: https://coverage.readthedocs.io/
- **Swagger/OpenAPI**: https://swagger.io/docs/
- **Docker Testing**: https://docs.docker.com/compose/
- **Factory Boy**: https://factoryboy.readthedocs.io/