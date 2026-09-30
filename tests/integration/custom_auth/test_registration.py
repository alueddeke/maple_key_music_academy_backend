"""
Integration tests for POST /api/auth/register/ (custom_auth/views/registration.py).

MAP-252: a submission that trips the "website" honeypot must be
indistinguishable from a real one — same status, same body — while storing
nothing and sending nothing.
"""
import logging

import pytest
from django.core import mail
from django.core.cache import caches
from django.urls import reverse

from billing.models import UserRegistrationRequest


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    caches['throttle'].clear()
    yield
    caches['throttle'].clear()


def _register(api_client, email, **extra):
    return api_client.post(reverse('register_with_email'), {
        'email': email,
        'first_name': 'Reg',
        'last_name': 'Test',
        'user_type': 'teacher',
        'website': '',
        **extra,
    }, format='json')


@pytest.mark.django_db
class TestRegistrationHoneypot:
    def test_honeypot_body_matches_real_path(self, api_client):
        real = _register(api_client, 'real.person@example.com')
        honeypot = _register(api_client, '  Bot.Test@Example.COM ',
                             website='http://spam.example')

        assert honeypot.status_code == real.status_code
        assert set(honeypot.json()) == set(real.json())
        assert honeypot.json()['message'] == real.json()['message']
        assert honeypot.json()['details'] == real.json()['details']
        # Echoed email is normalised exactly as the real path normalises it.
        assert real.json()['email'] == 'real.person@example.com'
        assert honeypot.json()['email'] == 'bot.test@example.com'

    def test_honeypot_stores_nothing_and_sends_nothing(self, api_client, caplog):
        before = UserRegistrationRequest.objects.count()

        with caplog.at_level(logging.WARNING, logger='custom_auth.views.registration'):
            _register(api_client, 'bot@example.com', website='http://spam.example')

        assert UserRegistrationRequest.objects.count() == before
        assert not UserRegistrationRequest.objects.filter(email='bot@example.com').exists()
        assert mail.outbox == []
        assert any('honeypot tripped' in r.getMessage() for r in caplog.records)
