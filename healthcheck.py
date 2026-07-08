"""Container healthcheck used by the prod docker run (deploy.yml --health-cmd).

The image has no curl, so this replaces the old curl-based check. Any HTTP
response at all (200/301/401 etc.) means Django is up; only a connection
failure or timeout marks the container unhealthy.
"""

import sys
import urllib.error
import urllib.request

try:
    urllib.request.urlopen("http://localhost:8000/api/auth/user/", timeout=5)
except urllib.error.HTTPError as e:
    sys.exit(0 if e.code in (200, 301, 401) else 1)
except Exception:
    sys.exit(1)
sys.exit(0)
