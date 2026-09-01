"""
Integration tests for the open-endpoint throttles (custom_auth/throttling.py).

Regression for the 2026-08-31 UAT finding D1/D2: the previous
ScopedRateThrottle subclasses silently allowed everything because the rate is
resolved from a view-level `throttle_scope` attribute the views never had.
These tests drive the real endpoints past their limits and assert 429.
"""
import pytest
from django.core.cache import caches
from django.urls import reverse
from rest_framework import status

from billing.models import ApprovedEmail, UserRegistrationRequest


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    caches['throttle'].clear()
    yield
    caches['throttle'].clear()


def _register(api_client, i):
    return api_client.post(reverse('register_with_email'), {
        'email': f'throttle.test.{i}@example.com',
        'first_name': 'Throttle',
        'last_name': f'Test{i}',
        'user_type': 'teacher',
    }, format='json')


@pytest.mark.django_db
class TestRegistrationThrottle:
    def test_sixth_registration_within_hour_is_throttled(self, api_client):
        for i in range(5):
            response = _register(api_client, i)
            assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS, (
                f'request {i + 1} throttled early: {response.status_code}'
            )
        response = _register(api_client, 5)
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_honeypot_requests_also_consume_the_rate(self, api_client):
        # A bot probing the honeypot must not get a fresh budget afterwards.
        for i in range(5):
            api_client.post(reverse('register_with_email'), {
                'email': f'bot.{i}@example.com',
                'website': 'http://spam.example',
            }, format='json')
        response = _register(api_client, 99)
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert not UserRegistrationRequest.objects.filter(
            email__startswith='bot.').exists()


@pytest.mark.django_db
class TestClientErrorThrottle:
    def test_thirty_first_beacon_within_hour_is_throttled(self, api_client):
        url = reverse('report_client_error')
        payload = {'message': 'boom', 'stack': '', 'url': 'http://x'}
        for i in range(30):
            response = api_client.post(url, payload, format='json')
            assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS, (
                f'request {i + 1} throttled early: {response.status_code}'
            )
        response = api_client.post(url, payload, format='json')
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
