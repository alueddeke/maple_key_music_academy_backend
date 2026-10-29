"""
Settings for the pytest run (pytest.ini DJANGO_SETTINGS_MODULE).

BillingConfig.ready() fails fast when the Helcim env vars are missing
(HELM-02). pytest-django imports this module before django.setup(), so the
test defaults land in time; a pytest hook (pytest_configure) runs after
django.setup() and is too late (MAP-201). setdefault never overrides values
the environment already provides (CI sets all four).
"""
import os

os.environ.setdefault('HELCIM_API_TOKEN', 'test-token')
os.environ.setdefault('HELCIM_TERMINAL_ID', 'test-terminal')
os.environ.setdefault('HELCIM_WEBHOOK_SECRET', 'dGVzdC1zZWNyZXQ=')  # base64('test-secret')  gitleaks:allow
os.environ.setdefault('HELCIM_SUBDOMAIN', 'testschool')

from .settings import *  # noqa: E402,F401,F403
