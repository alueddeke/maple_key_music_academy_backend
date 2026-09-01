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
