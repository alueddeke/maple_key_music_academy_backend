# Billing API Testing Guide

## Overview

This guide explains the comprehensive unit tests created for the billing API and how to run them.

## Test Structure

### 1. Unit Tests (`BillingUnitTests`)
Tests individual functions and business logic in isolation:
- Student creation logic
- Lesson cost calculations
- Invoice payment balance calculations
- Data validation

### 2. API Tests (`BillingAPITests`)
Tests the full API endpoints with real HTTP requests:
- Authentication and authorization
- Request/response handling
- Error scenarios
- Edge cases

## Edge Cases Covered

### Student Creation Edge Cases
1. **Duplicate Names**: What happens when two students have the same name?
2. **Duplicate Emails**: Handling when temporary emails already exist
3. **Special Characters**: Names with apostrophes, hyphens, accents
4. **Unicode Characters**: International names (Chinese, Arabic, etc.)
5. **Very Long Names**: Extremely long student names
6. **Empty Names**: Handling empty or whitespace-only names

### Lesson Data Edge Cases
1. **Negative Duration**: What happens with negative lesson durations?
2. **Zero Duration**: Handling zero-duration lessons
3. **Very High Duration**: Extremely long lesson durations
4. **Invalid Data Types**: Non-numeric duration values
5. **Missing Required Fields**: Requests without required data

### Authentication & Authorization Edge Cases
1. **No Authentication**: Requests without auth tokens
2. **Invalid Tokens**: Malformed or expired tokens
3. **Wrong User Types**: Students trying to submit teacher invoices
4. **Unauthorized Access**: Accessing endpoints without proper permissions

### Data Validation Edge Cases
1. **Malformed JSON**: Invalid JSON in request bodies
2. **Missing Fields**: Requests with missing required fields
3. **Invalid Field Values**: Out-of-range or invalid data types
4. **SQL Injection**: Attempts to inject malicious SQL
5. **XSS Attempts**: Cross-site scripting attempts in text fields

### Business Logic Edge Cases
1. **Empty Lesson Lists**: Submitting invoices with no lessons
2. **Mixed Student Types**: Mix of new and existing students
3. **Rate Calculations**: Edge cases in cost calculations
4. **Invoice Status Transitions**: Valid and invalid status changes
5. **Concurrent Access**: Multiple users accessing same resources

## Running the Tests

### Install Dependencies
```bash
cd maple_key_music_academy_backend
pip install -r requirements.txt
```

### Run All Tests
```bash
pytest billing/tests.py -v
```

### Run Specific Test Categories
```bash
# Run only unit tests
pytest billing/tests.py::BillingUnitTests -v

# Run only API tests
pytest billing/tests.py::BillingAPITests -v

# Run tests with specific markers
pytest billing/tests.py -m unit -v
```

### Run Tests with Coverage
```bash
# Install coverage tools
pip install pytest-cov coverage

# Run tests with coverage
pytest billing/tests.py --cov=billing --cov-report=html --cov-report=term

# Generate detailed coverage report
coverage run --source=billing manage.py test billing.tests
coverage report
coverage html  # Creates htmlcov/index.html
```

### Coverage Commands Explained
```bash
# Basic coverage
pytest billing/tests.py --cov=billing

# Coverage with HTML report
pytest billing/tests.py --cov=billing --cov-report=html

# Coverage with terminal and HTML reports
pytest billing/tests.py --cov=billing --cov-report=term --cov-report=html

# Coverage with minimum threshold (fail if below 80%)
pytest billing/tests.py --cov=billing --cov-fail-under=80

# Coverage for specific modules
pytest billing/tests.py --cov=billing.views --cov=billing.models
```

## Test Data Setup

The tests use Django's test database, which is created fresh for each test run. Test data includes:

- **Users**: Teachers, students, and management users
- **Authentication**: JWT tokens for API testing
- **Lessons**: Sample lessons with various durations and rates
- **Invoices**: Test invoices in different states

## Key Testing Principles

### 1. **Isolation**
Each test is independent and doesn't affect others.

### 2. **Mocking**
External dependencies (like database queries) are mocked when testing business logic.

### 3. **Edge Cases**
Tests cover both happy paths and error conditions.

### 4. **Realistic Data**
Tests use realistic data that matches production scenarios.

### 5. **Performance**
Tests run quickly (unit tests should complete in milliseconds).

## Common Test Patterns

### Testing API Endpoints
```python
def test_endpoint_success(self):
    response = self.client.post('/api/endpoint/', data, format='json')
    self.assertEqual(response.status_code, 201)
    self.assertIn('expected_field', response.data)
```

### Testing Business Logic
```python
def test_calculation_logic(self):
    result = calculate_something(input_data)
    self.assertEqual(result, expected_result)
```

### Testing Error Handling
```python
def test_invalid_input(self):
    with self.assertRaises(ValueError):
        process_invalid_data(invalid_input)
```

## Benefits of This Testing Approach

1. **Early Bug Detection**: Catches issues before they reach production
2. **Regression Prevention**: Ensures fixes don't break existing functionality
3. **Documentation**: Tests serve as living documentation of expected behavior
4. **Confidence**: Allows safe refactoring and feature additions
5. **Edge Case Coverage**: Identifies and handles unusual scenarios

## Next Steps

1. **Run the tests** to ensure they pass
2. **Add more edge cases** as you discover them
3. **Set up CI/CD** to run tests automatically
4. **Add integration tests** for full workflow testing
5. **Add performance tests** for load testing

## Troubleshooting

### Common Issues
- **Database errors**: Ensure test database is properly configured
- **Authentication failures**: Check that test users are created correctly
- **Import errors**: Verify all dependencies are installed

### Debug Tips
- Use `pytest -s` to see print statements
- Use `pytest --pdb` to drop into debugger on failures
- Check test database state with Django shell
