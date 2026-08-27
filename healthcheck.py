"""Container healthcheck used by the prod docker run (deploy.yml --health-cmd).

The image has no curl, so this replaces the old curl-based check. Any HTTP
response at all (200/3xx/401 etc.) means Django is up; only a connection
failure or timeout marks the container unhealthy.

Redirects must NOT be followed: prod Django redirects http -> https, and
following it points urllib at https://localhost:8000, which speaks plain
HTTP and fails the TLS handshake (SSL WRONG_VERSION_NUMBER). A redirect
response is itself proof the app is serving.
"""

import sys
import urllib.error
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


try:
    opener = urllib.request.build_opener(_NoRedirect)
    opener.open("http://localhost:8000/api/auth/user/", timeout=5)
except urllib.error.HTTPError as e:
    sys.exit(0 if e.code in (200, 301, 302, 307, 308, 401) else 1)
except Exception:
    sys.exit(1)
sys.exit(0)
