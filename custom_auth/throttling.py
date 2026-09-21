"""
Throttles for the open (unauthenticated) endpoints.

Built on AnonRateThrottle, NOT ScopedRateThrottle: ScopedRateThrottle reads
`throttle_scope` off the *view* at request time and silently allows everything
when it's absent — which is exactly the bug the 2026-08-31 UAT found (18
consecutive registrations, zero 429s). AnonRateThrottle resolves its rate from
the class-level `scope` at init, so a missing rate fails loudly instead.

Counters live in the shared 'throttle' DatabaseCache (see settings.CACHES):
the default LocMem cache is per-gunicorn-worker, which would multiply every
rate by the worker count and reset it on deploy.
"""
from django.core.cache import caches
from rest_framework.throttling import AnonRateThrottle


class SharedAnonRateThrottle(AnonRateThrottle):
    @property
    def cache(self):
        return caches['throttle']


class RegistrationThrottle(SharedAnonRateThrottle):
    scope = 'registration'


class ClientErrorThrottle(SharedAnonRateThrottle):
    scope = 'client_errors'


class LoginIPThrottle(SharedAnonRateThrottle):
    """Per-IP rate for login, refresh and the password-reset endpoints (MAP-141)."""
    scope = 'login'


class LoginEmailThrottle(SharedAnonRateThrottle):
    """
    Per-email rate for login and password-reset (MAP-141): a credential-
    stuffing run against one account from many IPs hits this one. Requests
    that carry no email (validate/confirm, malformed bodies) return None and
    fall through to the IP throttle.
    """
    scope = 'login_email'

    def get_cache_key(self, request, view):
        email = str(request.data.get('email', '') or '').strip().lower()
        if not email:
            return None
        return f'throttle_login_email_{email}'
