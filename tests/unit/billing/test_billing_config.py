"""
Unit tests for BillingConfig.ready() env var validation (HELM-02).

These tests verify that Django startup raises ImproperlyConfigured if any of the
three required Helcim environment variables is missing.

Tests do NOT use @pytest.mark.django_db — they only exercise BillingConfig.ready().
Tests use mock.patch.dict(os.environ, ...) to safely isolate env state.
"""

import os
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured

# Import BillingConfig lazily inside tests to avoid triggering ready() at import time.
# We import billing.apps directly so we can call ready() manually.


def get_config():
    """Return a fresh BillingConfig instance for testing."""
    from billing.apps import BillingConfig
    return BillingConfig('billing', __import__('billing'))


class TestBillingConfigReady:
    """Tests for BillingConfig.ready() Helcim env var validation."""

    def test_ready_raises_when_api_token_missing(self):
        """Missing HELCIM_API_TOKEN must raise ImproperlyConfigured."""
        env = {
            'HELCIM_TERMINAL_ID': 'test-terminal',
            'HELCIM_WEBHOOK_SECRET': 'dGVzdC1zZWNyZXQ=',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop('HELCIM_API_TOKEN', None)
            config = get_config()
            with pytest.raises(ImproperlyConfigured) as exc_info:
                config.ready()
        assert 'HELCIM_API_TOKEN' in str(exc_info.value)

    def test_ready_raises_when_terminal_id_missing(self):
        """Missing HELCIM_TERMINAL_ID must raise ImproperlyConfigured."""
        env = {
            'HELCIM_API_TOKEN': 'test-token',
            'HELCIM_WEBHOOK_SECRET': 'dGVzdC1zZWNyZXQ=',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop('HELCIM_TERMINAL_ID', None)
            config = get_config()
            with pytest.raises(ImproperlyConfigured) as exc_info:
                config.ready()
        assert 'HELCIM_TERMINAL_ID' in str(exc_info.value)

    def test_ready_raises_when_webhook_secret_missing(self):
        """Missing HELCIM_WEBHOOK_SECRET must raise ImproperlyConfigured."""
        env = {
            'HELCIM_API_TOKEN': 'test-token',
            'HELCIM_TERMINAL_ID': 'test-terminal',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop('HELCIM_WEBHOOK_SECRET', None)
            config = get_config()
            with pytest.raises(ImproperlyConfigured) as exc_info:
                config.ready()
        assert 'HELCIM_WEBHOOK_SECRET' in str(exc_info.value)

    def test_ready_raises_when_subdomain_missing(self):
        """Missing HELCIM_SUBDOMAIN must raise ImproperlyConfigured (Phase 19 validation)."""
        env = {
            'HELCIM_API_TOKEN': 'test-token',
            'HELCIM_TERMINAL_ID': 'test-terminal',
            'HELCIM_WEBHOOK_SECRET': 'dGVzdC1zZWNyZXQ=',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop('HELCIM_SUBDOMAIN', None)
            config = get_config()
            with pytest.raises(ImproperlyConfigured) as exc_info:
                config.ready()
        assert 'HELCIM_SUBDOMAIN' in str(exc_info.value)

    def test_ready_passes_when_all_present(self):
        """ready() must not raise when all four env vars are set."""
        env = {
            'HELCIM_API_TOKEN': 'test-token',
            'HELCIM_TERMINAL_ID': 'test-terminal',
            'HELCIM_WEBHOOK_SECRET': 'dGVzdC1zZWNyZXQ=',
            'HELCIM_SUBDOMAIN': 'testschool',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            config = get_config()
            # Should not raise
            config.ready()
