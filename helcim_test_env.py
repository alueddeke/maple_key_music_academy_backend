"""
pytest plugin: sets Helcim test env vars before Django boots.

Registered via pytest.ini addopts: -p helcim_test_env
pytest loads -p plugins before pytest-django calls django.setup(), so
BillingConfig.ready() does not raise ImproperlyConfigured during test collection.
"""
import os


def pytest_configure(config):
    os.environ.setdefault('HELCIM_API_TOKEN', 'test-token')
    os.environ.setdefault('HELCIM_TERMINAL_ID', 'test-terminal')
    os.environ.setdefault('HELCIM_WEBHOOK_SECRET', 'dGVzdC1zZWNyZXQ=')  # base64('test-secret')
    os.environ.setdefault('HELCIM_SUBDOMAIN', 'testschool')  # Phase 19: required for payment URL construction
