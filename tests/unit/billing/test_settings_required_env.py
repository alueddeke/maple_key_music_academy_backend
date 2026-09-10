"""
Boundary tests for required environment variables (MAP-181).

Each test boots the project in a subprocess (``manage.py check``) with a
controlled environment and asserts the process outcome — exit code and the
variable named on stderr — never the presence of a literal in settings.py.

The base environment is inherited from the running test process (env.dev in
the api container, ci.yml / deploy.yml in CI), so no dev value is hard-coded
here.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANAGE_PY = REPO_ROOT / 'manage.py'

# The six settings the ticket requires with no default.
REQUIRED_ENV_VARS = [
    'DEBUG',
    'FRONTEND_URL',
    'CORS_ALLOWED_ORIGINS',
    'ALLOWED_HOSTS',
    'SECRET_KEY',
    'DATABASE_URL',
]


def _boot(env):
    return subprocess.run(
        [sys.executable, str(MANAGE_PY), 'check'],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope='module')
def no_dotenv_fallback():
    """python-decouple silently reads a .env file next to the project when a
    variable is absent from the environment. That would mask the
    missing-variable failures asserted below, so fail loudly — never skip."""
    dotenv = REPO_ROOT / '.env'
    assert not dotenv.exists(), (
        f"{dotenv} exists; python-decouple would read it as a fallback and mask "
        "missing-variable failures. Move it aside before running these tests."
    )


@pytest.fixture
def complete_env(no_dotenv_fallback):
    env = dict(os.environ)
    missing = [name for name in REQUIRED_ENV_VARS if name not in env]
    assert not missing, f"test runner environment lacks required vars: {missing}"
    env.pop('MAPLEKEY_ENV', None)
    return env


def test_boot_succeeds_with_complete_env(complete_env):
    result = _boot(complete_env)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('name', REQUIRED_ENV_VARS)
def test_boot_fails_when_required_var_missing(complete_env, name):
    env = dict(complete_env)
    del env[name]

    result = _boot(env)

    assert result.returncode != 0
    assert name in result.stderr


def test_boot_refuses_debug_true_in_prod(complete_env):
    env = dict(complete_env, MAPLEKEY_ENV='prod', DEBUG='True')

    result = _boot(env)

    assert result.returncode != 0
    assert 'DEBUG' in result.stderr


def test_boot_refuses_cors_wildcard(complete_env):
    env = dict(complete_env, CORS_ALLOWED_ORIGINS='*')

    result = _boot(env)

    assert result.returncode != 0
    assert 'CORS_ALLOWED_ORIGINS' in result.stderr


@pytest.mark.parametrize('value', ['', ','])
def test_boot_refuses_empty_cors(complete_env, value):
    """An empty or all-blank origin list is not a configured CORS policy."""
    env = dict(complete_env, CORS_ALLOWED_ORIGINS=value)

    result = _boot(env)

    assert result.returncode != 0
    assert 'CORS_ALLOWED_ORIGINS' in result.stderr
