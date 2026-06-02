"""
Root-level pytest configuration.

This file is intentionally minimal. Env var defaults for Helcim credentials
are set by helcim_test_env.py (loaded via addopts: -p helcim_test_env in pytest.ini),
which fires before pytest-django calls django.setup() — ensuring BillingConfig.ready()
does not raise ImproperlyConfigured during test collection (HELM-02 Pitfall 1 fix).

Test fixtures are in tests/conftest.py.
"""
