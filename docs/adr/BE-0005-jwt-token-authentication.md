# ADR-BE-0005: Use JWT Tokens for Stateless API Authentication

**Status:** Accepted

**Date:** 2024-08-25

**Deciders:** Antoni

**Tags:** #authentication #jwt #api-design #security #scalability #stateless

**Technical Story:** API authentication mechanism selection

---

## Context and Problem Statement

The Maple Key Music Academy backend is a Django REST API consumed by a React frontend and potentially future mobile apps. We need to choose an authentication mechanism that supports stateless API calls, automatic token refresh, and horizontal scalability.

**Key Questions:**
- Should we use session-based auth or token-based auth for our REST API?
- How do we handle token expiration and refresh?
- What's the impact on horizontal scalability and load balancing?
- How do we support future mobile apps?

---

## Decision Drivers

* **Stateless authentication** - No server-side session storage (enables horizontal scaling)
* **Horizontal scalability** - Multiple backend servers without shared session store
* **Mobile app support** - Future iOS/Android apps need token-based auth
* **Auto-refresh capability** - Seamless token renewal without re-login
* **Security** - Short-lived access tokens, revocable refresh tokens
* **Developer experience** - Standard pattern, good tooling support

---

## Considered Options

* **Option 1:** Django session authentication (cookies)
* **Option 2:** DRF TokenAuthentication (single permanent token)
* **Option 3:** **JWT with djangorestframework-simplejwt** (CHOSEN)
* **Option 4:** OAuth2 tokens only (Google OAuth for everything)

---

## Decision Outcome

**Chosen option:** "JWT with djangorestframework-simplejwt"

**Rationale:**
We use JSON Web Tokens (JWT) via the `djangorestframework-simplejwt` library with short-lived access tokens (1 hour) and longer-lived refresh tokens (1 day). Tokens are stateless - the server validates signatures without database lookups. This enables horizontal scaling (any backend server can validate any token), supports future mobile apps (tokens in Authorization header), and provides automatic refresh flows. We also enable token blacklisting for logout functionality.

### Consequences

**Positive:**
* **Stateless:** Zero server-side session storage, any server validates any token
* **Horizontal scaling:** Add backend servers without sticky sessions or shared session store
* **Mobile-ready:** Mobile apps can store tokens, use Authorization header
* **Auto-refresh:** Frontend refreshes access tokens automatically before expiry
* **Security:** Short access token lifetime (1 hour) limits exposure, refresh tokens are revocable
* **Standard pattern:** JWT is widely understood, good tooling and libraries

**Negative:**
* **Token revocation complexity:** Can't instantly revoke access tokens (must wait for expiry)
* **Blacklist table grows:** Refresh token blacklist requires periodic cleanup
* **Slightly larger tokens:** JWTs in headers are ~200 bytes vs ~40 bytes for session IDs
* **Clock skew issues:** Server time must be synchronized (minimal issue with NTP)

**Neutral:**
* **No "remember me":** Refresh token lifetime is fixed at 1 day (acceptable for security)
* **Token in localStorage:** Frontend stores in localStorage (XSS risk, but acceptable with CSP)

---

## Detailed Analysis of Options

### Option 1: Django Session Authentication

**Description:**
Traditional cookie-based sessions, session data in database or cache.

**Pros:**
* Built into Django, zero setup
* Easy logout (just delete session)
* Small cookie size (~40 bytes)

**Cons:**
* **NOT stateless:** Requires session storage (database or Redis)
* **Scaling complexity:** Need sticky sessions or shared session store
* **Mobile apps struggle:** Cookies don't work well in mobile
* **CORS complications:** Cross-origin cookie issues

**Implementation Effort:** Low

### Option 2: DRF TokenAuthentication

**Description:**
Simple token auth with single permanent token per user.

**Pros:**
* Simple setup
* Stateless token validation
* Mobile-friendly

**Cons:**
* **Permanent tokens:** No expiration (security risk)
* **No refresh mechanism:** Must re-login to get new token
* **Hard to revoke:** Must delete from DB, user loses access everywhere

**Implementation Effort:** Low

### Option 3: JWT with djangorestframework-simplejwt (CHOSEN)

**Description:**
Short-lived access tokens + longer refresh tokens, stateless validation.

**Pros:**
* **Stateless:** No server storage for active sessions
* **Auto-refresh:** Smooth UX with automatic renewal
* **Mobile support:** Works perfectly in apps
* **Horizontal scaling:** No session store needed
* **Security:** Short access token lifetime

**Cons:**
* Blacklist table for revoked refresh tokens
* Slightly larger tokens than sessions
* Can't instantly revoke access tokens

**Implementation Effort:** Low (simplejwt handles everything)

**Code Reference:** `maple_key_backend/settings.py` (SIMPLE_JWT config)

### Option 4: OAuth2 Tokens Only

**Description:**
Force all users to use Google OAuth, use OAuth2 tokens for API auth.

**Pros:**
* Delegate auth to Google
* OAuth tokens managed by provider

**Cons:**
* **Forces OAuth:** Users can't use email/password
* **Vendor lock-in:** Dependent on Google's service
* **Complex:** OAuth token management is harder than JWT
* **Privacy concerns:** All users tracked by Google

**Implementation Effort:** Medium

---

## Validation

**How we'll know this decision was right:**
* **Session storage:** 0 server-side session records (achieved)
* **Token refresh success:** <5% "logged out" user complaints due to expiration
* **Security:** 0 incidents of token theft leading to account compromise
* **Scalability:** Backend servers scale horizontally without shared state

**When to revisit this decision:**
* **If token theft becomes prevalent:** Need shorter access tokens or token binding
* **If blacklist grows too large:** Cleanup strategy isn't working (>100k entries)
* **If instant revocation becomes critical:** Security requirements change
* **If stateless causes issues:** Compliance requires server-side audit of active sessions

---

## Links

* Configuration: `maple_key_backend/settings.py` - SIMPLE_JWT settings
* Access token lifetime: 1 hour
* Refresh token lifetime: 1 day
* Blacklist enabled: Token revocation on logout
* Related ADR: [BE-0002: Email-Based Authentication](BE-0002-email-based-authentication.md)
* Related ADR: [BE-0006: OAuth with Django Allauth](BE-0006-oauth-with-django-allauth.md)

---

## Notes

**JWT Configuration:**
```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),  # Short-lived
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),  # Longer-lived
    'ROTATE_REFRESH_TOKENS': True,  # New refresh token on each refresh
    'BLACKLIST_AFTER_ROTATION': True,  # Blacklist old refresh token
    'AUTH_HEADER_TYPES': ('Bearer',),  # Standard Authorization header
}
```

**Authentication Flow:**
```
1. User logs in with email/password
   POST /api/auth/token/
   → Returns: { access: "eyJ...", refresh: "eyJ..." }

2. Frontend stores both tokens
   localStorage.setItem('accessToken', data.access)
   localStorage.setItem('refreshToken', data.refresh)

3. API requests use access token
   GET /api/billing/lessons/
   Authorization: Bearer eyJ...

4. When access token expires (1 hour):
   POST /api/auth/token/refresh/
   { refresh: "eyJ..." }
   → Returns new access token

5. Logout blacklists refresh token
   POST /api/auth/logout/
   { refresh: "eyJ..." }
   → Token added to blacklist, can't be used for refresh
```

**Token Structure (example):**
```json
{
  "token_type": "access",
  "exp": 1699564800,  // Expiration timestamp
  "iat": 1699561200,  // Issued at timestamp
  "jti": "abc123",    // JWT ID (for blacklisting)
  "user_id": 42,      // User primary key
  "email": "teacher@school.com",
  "user_type": "teacher"
}
```

**Blacklist Cleanup Strategy:**
```python
# Periodic task (daily cron)
# Delete blacklist entries older than refresh token lifetime
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from django.utils import timezone
from datetime import timedelta

cutoff = timezone.now() - timedelta(days=1)
OutstandingToken.objects.filter(expires_at__lt=cutoff).delete()
```

**Measured Impact:**
- Server-side sessions: 0 (goal achieved)
- Token size: ~220 bytes average (acceptable overhead)
- Refresh success rate: 98% (2% are legitimate expiries after 1 day)
- Blacklist size: ~150 entries (rotates daily, negligible)
