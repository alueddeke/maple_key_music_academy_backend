# Maple Key Music Academy - Testing Workflow

## 🎯 **Docker-First Testing Approach**

This follows your existing team workflow and keeps everything consistent with your Docker setup, now including comprehensive Swagger documentation testing.

## 🚀 **Running Tests (Docker Way)**

### **Option 1: Test Inside Running Container**
```bash
# Start your development environment
cd maple_key_music_academy_docker
docker-compose up -d

# Run tests inside the API container
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=term --cov-report=html

# Run Swagger tests
docker-compose exec api pytest tests/test_swagger_basic.py -v
```

### **Option 2: Dedicated Testing Service**
```bash
# Run comprehensive test suite with coverage
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=html --cov-report=term --junitxml=test_reports/junit.xml --html=test_reports/report.html --self-contained-html

# Run Swagger functionality tests
docker-compose --profile testing run --rm api-tests python manage.py test tests.test_swagger_basic --verbosity=2
```

### **Option 3: Development Testing**
```bash
# Run tests every time you make changes
docker-compose exec api pytest billing/tests.py -v

# Run with coverage
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html
```

## 🔧 **Development Workflow with Testing**

### **Daily Development:**
```bash
# 1. Start development environment
cd maple_key_music_academy_docker
docker-compose up -d

# 2. Make code changes
# (your changes are automatically reflected)

# 3. Run tests
docker-compose exec api pytest billing/tests.py -v

# 4. Run with coverage
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html

# 5. Test Swagger documentation
docker-compose exec api pytest tests/test_swagger_basic.py -v
```

### **When Adding New Dependencies:**
```bash
# 1. Add to requirements.txt (like you did)
# 2. Commit and push
git add requirements.txt
git commit -m "Add testing dependencies"
git push origin feature-branch

# 3. Team members rebuild (as per your workflow guide)
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## 📋 **Testing Commands**

### **Basic Testing:**
```bash
# Run all tests
docker-compose exec api pytest billing/tests.py

# Run with verbose output
docker-compose exec api pytest billing/tests.py -v

# Run specific test
docker-compose exec api pytest billing/tests.py::BillingUnitTests::test_student_creation
```

### **Coverage Testing:**
```bash
# Run with coverage
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=term

# Generate HTML coverage report
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html

# View coverage report
open htmlcov/index.html  # (from your host machine)
```

### **Swagger Testing:**
```bash
# Test Swagger functionality
docker-compose exec api pytest tests/test_swagger_basic.py -v

# Test Swagger UI accessibility
docker-compose exec api pytest tests/test_swagger_basic.py::SwaggerBasicTests::test_swagger_ui_accessible -v

# Test OpenAPI schema generation
docker-compose exec api pytest tests/test_swagger_basic.py::SwaggerBasicTests::test_openapi_schema_accessible -v
```

### **Django Test Runner:**
```bash
# Use Django's built-in test runner
docker-compose exec api python manage.py test --verbosity=2

# Run specific Django tests
docker-compose exec api python manage.py test tests.test_swagger_basic --verbosity=2
```

### **Testing Specific Areas:**
```bash
# Test only unit tests
docker-compose exec api pytest billing/tests.py::BillingUnitTests

# Test only API tests
docker-compose exec api pytest billing/tests.py::BillingAPITests

# Test only Swagger tests
docker-compose exec api pytest tests/test_swagger_basic.py

# Test with specific markers
docker-compose exec api pytest billing/tests.py -m unit
```

## 🎯 **Swagger Documentation Testing**

### **Access Swagger Documentation:**
```bash
# Start development environment
docker-compose up -d

# Access documentation
# Swagger UI: http://localhost:8000/api/docs/
# ReDoc: http://localhost:8000/api/redoc/
# OpenAPI Schema: http://localhost:8000/api/schema/
```

### **Test Swagger Functionality:**
```bash
# Test basic Swagger functionality
docker-compose exec api python manage.py test tests.test_swagger_basic --verbosity=2

# Test Swagger UI accessibility
docker-compose exec api python manage.py test tests.test_swagger_basic.SwaggerBasicTests.test_swagger_ui_accessible --verbosity=2

# Test OpenAPI schema generation
docker-compose exec api python manage.py test tests.test_swagger_basic.SwaggerBasicTests.test_openapi_schema_accessible --verbosity=2
```

### **Interactive Testing:**
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

## 🔧 **Comprehensive Testing Commands**

### **Full Test Suite:**
```bash
# Run all tests with comprehensive reporting
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=html --cov-report=term --junitxml=test_reports/junit.xml --html=test_reports/report.html --self-contained-html

# Run with verbose output
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=html --cov-report=term -v
```

### **Specific Test Categories:**
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

### **Service Testing:**
```bash
# Test billing services
docker-compose --profile testing run --rm api-tests pytest billing/test_services.py -v

# Test with coverage
docker-compose --profile testing run --rm api-tests pytest billing/test_services.py --cov=billing --cov-report=html
```

## 🎯 **Benefits of Docker-First Testing**

1. **Consistent Environment**: Same Python version, same dependencies
2. **Team Consistency**: Everyone runs tests the same way
3. **No Local Conflicts**: No virtual environment issues
4. **Easy CI/CD**: Same commands work in production
5. **Database Access**: Tests can use the same database setup
6. **Swagger Integration**: API documentation testing included
7. **Comprehensive Coverage**: Unit, integration, and contract testing

## 🚨 **Important Notes**

- **Don't use local virtual environment** - It breaks your team workflow
- **Always test inside Docker** - Keeps everything consistent
- **Coverage reports are generated inside container** - Access via volumes
- **Database is shared** - Tests use the same database as development
- **Swagger tests validate documentation** - Ensures API docs stay accurate
- **Contract testing prevents breaking changes** - Catches API regressions

## 🔍 **Troubleshooting**

### **If tests fail:**
```bash
# Check container logs
docker-compose logs api

# Rebuild if dependencies changed
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### **If coverage reports don't appear:**
```bash
# Check if htmlcov directory exists
docker-compose exec api ls -la

# Generate coverage report
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html
```

### **If Swagger tests fail:**
```bash
# Check Swagger configuration
docker-compose exec api python manage.py shell -c "from drf_spectacular.utils import extend_schema; print('Swagger configured')"

# Test Swagger endpoints directly
curl http://localhost:8000/api/schema/
curl http://localhost:8000/api/docs/
curl http://localhost:8000/api/redoc/
```

### **If database issues:**
```bash
# Check database volume
docker volume ls | grep postgres

# Database is safe in the volume!
```

## 📞 **Quick Reference**

```bash
# Start development
cd maple_key_music_academy_docker
docker-compose up -d

# Run basic tests
docker-compose exec api pytest billing/tests.py --cov=billing --cov-report=html

# Run Swagger tests
docker-compose exec api pytest tests/test_swagger_basic.py -v

# Run comprehensive test suite
docker-compose --profile testing run --rm api-tests pytest --cov=. --cov-report=html --cov-report=term

# View coverage
open htmlcov/index.html

# Access Swagger documentation
# http://localhost:8000/api/docs/
# http://localhost:8000/api/redoc/
# http://localhost:8000/api/schema/
```

## 🎯 **Testing Workflow Summary**

1. **Development**: Make code changes
2. **Unit Tests**: Test individual components
3. **Integration Tests**: Test component interactions
4. **Swagger Tests**: Validate API documentation
5. **Coverage**: Ensure comprehensive testing
6. **Documentation**: Keep API docs up to date

---

**This approach respects your existing Docker workflow while adding comprehensive testing including Swagger documentation validation! 🎵**