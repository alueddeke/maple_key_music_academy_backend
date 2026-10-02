"""
Route-auth manifest test (MAP-143).

Every route in the project URLconf must appear in
custom_auth/route_manifest.py, and every route must behave the way its entry
says when called through the real stack:

- anonymous → 401 on every method of every non-PUBLIC route;
- a role outside the route's set → 403;
- a role inside the set → anything but 401/403 (400/404/405 are fine — the
  test never creates the target row; it only proves the auth gate opens).

This is the guard against the SEC-03 regression class: a refactor that drops
a role decorator turns one of these assertions red. Ownership (teacher A vs
teacher B) and school scoping are out of scope; `teacher_id` path arguments
are filled with the caller's own pk so the ownership check cannot pose as a
role 403.

Each request runs inside a savepoint that is rolled back, so one route's side
effects (or a DB error) never leak into the next request.
"""
import re

import pytest
from django.core.cache import caches
from django.db import transaction
from rest_framework import status
from rest_framework.test import APIClient

from custom_auth.route_manifest import (
    ALL_ROLES,
    INFRA,
    MANAGEMENT,
    PUBLIC,
    ROUTE_MANIFEST,
    STUDENT,
    TEACHER,
    iter_routes,
)

ROUTES = list(iter_routes())
ROUTES_BY_NAME = {route.name: route for route in ROUTES}

AUTH_DENIED = (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
PAYMENT_CALLBACK = 'payment_callback'

PATH_ARG = re.compile(r'<(?:(?P<converter>[^>:]+):)?(?P<name>[^>]+)>')


def _protected_routes():
    return [
        route for route in ROUTES
        if isinstance(ROUTE_MANIFEST.get(route.name), frozenset)
    ]


def _url(route, user=None):
    def fill(match):
        if match.group('name') == 'teacher_id' and user is not None:
            return str(user.pk)
        return 'x' if match.group('converter') == 'str' else '1'
    return '/' + PATH_ARG.sub(fill, route.path)


def _call(client, route, method, user=None):
    """Send one request; roll back whatever the view did."""
    sid = transaction.savepoint()
    try:
        response = getattr(client, method.lower())(
            _url(route, user), {}, format='json'
        )
    finally:
        transaction.savepoint_rollback(sid)
    return response.status_code


def _client(user=None):
    client = APIClient(raise_request_exception=False)
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _report(failures):
    return '\n'.join(
        f'{name} {method} as {who}: got {code} ({ROUTES_BY_NAME[name].source()})'
        for name, method, who, code in failures
    )


@pytest.fixture(autouse=True)
def clear_throttle_cache(request):
    if 'django_db' not in request.keywords:
        yield
        return
    # Open endpoints carry AnonRateThrottle subclasses; each anonymous request
    # here hits one route at most once per method, well under every rate, as
    # long as no earlier test left counters behind.
    caches['throttle'].clear()
    yield
    caches['throttle'].clear()


@pytest.fixture
def principals(management_user, teacher_user, student_user):
    return {
        MANAGEMENT: management_user,
        TEACHER: teacher_user,
        STUDENT: student_user,
    }


def test_manifest_roles_are_known():
    unknown = {
        name: value for name, value in ROUTE_MANIFEST.items()
        if value not in (PUBLIC, INFRA)
        and not (isinstance(value, frozenset) and value and value <= ALL_ROLES)
    }
    assert not unknown, f'manifest entries with invalid values: {unknown}'


def test_every_resolver_route_is_in_manifest():
    missing = sorted(
        f'{route.name or "<unnamed>"} ({route.path})'
        for route in ROUTES if route.name not in ROUTE_MANIFEST
    )
    assert not missing, (
        'routes with no auth declaration in custom_auth/route_manifest.py:\n'
        + '\n'.join(missing)
    )


def test_every_manifest_entry_exists_in_resolver():
    stale = sorted(set(ROUTE_MANIFEST) - set(ROUTES_BY_NAME))
    assert not stale, f'manifest entries that no longer resolve: {stale}'


@pytest.mark.django_db
def test_anonymous_gets_401_on_every_protected_route():
    client = _client()
    failures = [
        (route.name, method, 'anonymous', code)
        for route in _protected_routes()
        for method in route.methods
        if (code := _call(client, route, method)) != status.HTTP_401_UNAUTHORIZED
    ]
    assert not failures, _report(failures)


@pytest.mark.django_db
def test_public_routes_are_reachable_anonymously():
    client = _client()
    failures = [
        (route.name, method, 'anonymous', code)
        for route in ROUTES
        if ROUTE_MANIFEST.get(route.name) == PUBLIC and route.name != PAYMENT_CALLBACK
        for method in route.methods
        if (code := _call(client, route, method))
        in AUTH_DENIED + (status.HTTP_429_TOO_MANY_REQUESTS,)
    ]
    assert not failures, _report(failures)


@pytest.mark.django_db
def test_payment_callback_rejects_unsigned_post():
    code = _call(_client(), ROUTES_BY_NAME[PAYMENT_CALLBACK], 'POST')
    assert code in (
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


@pytest.mark.django_db
@pytest.mark.parametrize('role', [STUDENT, TEACHER, MANAGEMENT])
def test_role_outside_set_gets_403(role, principals):
    user = principals[role]
    client = _client(user)
    failures = [
        (route.name, method, role, code)
        for route in _protected_routes()
        if role not in ROUTE_MANIFEST[route.name]
        for method in route.methods
        if (code := _call(client, route, method, user)) != status.HTTP_403_FORBIDDEN
    ]
    assert not failures, _report(failures)


@pytest.mark.django_db
@pytest.mark.parametrize('role', [STUDENT, TEACHER, MANAGEMENT])
def test_role_inside_set_passes_auth_gate(role, principals):
    user = principals[role]
    client = _client(user)
    failures = [
        (route.name, method, role, code)
        for route in _protected_routes()
        if role in ROUTE_MANIFEST[route.name]
        for method in route.methods
        if (code := _call(client, route, method, user)) in AUTH_DENIED
    ]
    assert not failures, _report(failures)
