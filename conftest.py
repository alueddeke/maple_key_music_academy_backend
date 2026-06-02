"""
Root-level pytest configuration.

The pytest_configure hook here sets Helcim env var defaults before
pytest-django calls django.setup() via pytest_load_initial_conftests.
Root conftest pytest_configure fires during _preparse, which is earlier
than pytest_load_initial_conftests — so BillingConfig.ready() does not
raise ImproperlyConfigured during test collection (HELM-02 Pitfall 1 fix).

Test fixtures are in tests/conftest.py.
"""
import os


def pytest_configure(config):
    """Set Helcim test env vars before Django boots."""
    os.environ.setdefault("HELCIM_API_TOKEN", "test-token")
    os.environ.setdefault("HELCIM_TERMINAL_ID", "test-terminal")
    os.environ.setdefault("HELCIM_WEBHOOK_SECRET", "dGVzdC1zZWNyZXQ=")  # base64('test-secret')
