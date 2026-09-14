"""
Integration tests for the open-endpoint throttles (custom_auth/throttling.py).

Regression for the 2026-08-31 UAT finding D1/D2: the previous
ScopedRateThrottle subclasses silently allowed everything because the rate is
resolved from a view-level `throttle_scope` attribute the views never had.
These tests drive the real endpoints past their limits and assert 429.
"""
import pytest
from django.conf import settings
from django.core.cache import caches
from django.urls import reverse
from rest_framework import status

from billing.models import ApprovedEmail, UserRegistrationRequest
from custom_auth.throttling import LoginIPThrottle


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


# ---------------------------------------------------------------------------
# MAP-141: login / refresh / password-reset throttles. Limits are read from
# DEFAULT_THROTTLE_RATES and parsed by the throttle itself — never literals.
# ---------------------------------------------------------------------------

def _limit(scope):
    rate = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'][scope]
    num_requests, _period = LoginIPThrottle().parse_rate(rate)
    return num_requests


def _login(api_client, email, password, ip=None):
    extra = {'HTTP_X_FORWARDED_FOR': ip} if ip else {}
    return api_client.post(
        reverse('get_jwt_token'), {'email': email, 'password': password},
        format='json', **extra,
    )


@pytest.mark.django_db
class TestLoginThrottle:
    def test_ip_limit_plus_one_is_throttled(self, api_client):
        """Beyond the per-IP login rate from one IP → 429 (distinct emails stay under the email rate)."""
        limit = _limit('login')
        for i in range(limit):
            response = _login(api_client, f'nobody{i}@example.com', 'wrong')
            assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS, (
                f'request {i + 1} throttled early: {response.status_code}'
            )
        response = _login(api_client, f'nobody{limit}@example.com', 'wrong')
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_email_limit_across_ips_then_other_email_same_ip_succeeds(self, api_client, teacher_user):
        """Beyond the per-email rate for one email across IPs → 429; another email from that IP, under the IP rate → 200."""
        limit = _limit('login_email')
        assert limit < _limit('login')  # the email rate is the tighter one
        for i in range(limit):
            response = _login(api_client, 'target@example.com', 'wrong', ip=f'10.0.0.{i + 1}')
            assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS
        last_ip = f'10.0.0.{limit + 1}'
        response = _login(api_client, 'target@example.com', 'wrong', ip=last_ip)
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

        response = _login(api_client, teacher_user.email, 'testpass123', ip=last_ip)
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestRefreshThrottle:
    def test_ip_limit_plus_one_is_throttled(self, api_client):
        limit = _limit('login')
        url = reverse('refresh_jwt_token')
        for i in range(limit):
            response = api_client.post(url, {'refresh': 'not-a-token'}, format='json')
            assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS
        response = api_client.post(url, {'refresh': 'not-a-token'}, format='json')
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
class TestPasswordResetThrottle:
    def test_request_email_limit_plus_one_is_throttled(self, api_client):
        limit = _limit('login_email')
        url = reverse('password_reset_request')
        for i in range(limit):
            response = api_client.post(url, {'email': 'someone@example.com'}, format='json',
                                       HTTP_X_FORWARDED_FOR=f'10.1.0.{i + 1}')
            assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS
        response = api_client.post(url, {'email': 'someone@example.com'}, format='json',
                                   HTTP_X_FORWARDED_FOR=f'10.1.0.{limit + 1}')
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_confirm_ip_limit_plus_one_is_throttled(self, api_client):
        limit = _limit('login')
        url = reverse('password_reset_confirm')
        payload = {'uid': 'x', 'token': 'y', 'password': 'a', 'confirm_password': 'a'}
        for i in range(limit):
            response = api_client.post(url, payload, format='json')
            assert response.status_code != status.HTTP_429_TOO_MANY_REQUESTS
        response = api_client.post(url, payload, format='json')
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
