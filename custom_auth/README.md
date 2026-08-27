# Custom Auth App

The Custom Auth app handles authentication, authorization, and user session management for the Maple Key Music Academy backend.

## Architecture Overview

This app provides:
- **Google OAuth with PKCE** — SPA-driven OAuth 2.0 (RFC 7636); backend exchanges the authorization code, never handles a redirect
- **JWT Token Authentication** — email/password login with SimpleJWT access/refresh tokens
- **Registration + approval workflow** — new users submit a registration request; management approves before any login works
- **Password reset** — token-based email reset flow
- **Role-Based Authorization** — decorators for teacher/management/student permission levels

Views live in the `custom_auth/views/` package: `oauth.py`, `jwt_auth.py`, `registration.py`, `password_reset.py`, `profile.py`.

## Endpoints

All routes are mounted under `/api/auth/` (see `custom_auth/urls.py`):

| Method | Endpoint | View | Purpose |
|--------|----------|------|---------|
| POST | `/api/auth/google/exchange/` | `google_exchange` | PKCE code exchange → JWT pair |
| POST | `/api/auth/register/` | `register_with_email` | Submit registration request (no password) |
| POST | `/api/auth/token/` | `get_jwt_token` | Email/password login → JWT pair |
| POST | `/api/auth/token/refresh/` | `refresh_jwt_token` | Refresh access token |
| GET | `/api/auth/user/` | `user_profile` | Current user profile (requires Bearer token) |
| POST | `/api/auth/logout/` | `logout` | Blacklist refresh token |
| POST | `/api/auth/password-reset/` | `password_reset_request` | Send reset email |
| POST | `/api/auth/password-reset/validate/` | `password_reset_validate_token` | Validate reset token before showing form |
| POST | `/api/auth/password-reset/confirm/` | `password_reset_confirm` | Set new password |

## Google OAuth (PKCE)

The old redirect-based flow (`google/`, `google/callback/`) and django-allauth are gone. The current flow is frontend-driven PKCE — tokens never appear in URLs (SEC-01). Full rationale: `.planning/codebase/SECURITY.md`.

```
1. Frontend generates code_verifier (sessionStorage: pkce_code_verifier)
   and state (sessionStorage: pkce_oauth_state)
2. Frontend sends code_challenge = SHA-256(code_verifier) to Google
3. Google redirects back to the SPA with an authorization code (safe to log)
4. Frontend POSTs { code, code_verifier } to /api/auth/google/exchange/
5. Backend exchanges the code with Google (server-to-server, timeout=10s),
   fetches userinfo, finds/creates the user
6. Backend returns { access_token, refresh_token, user } in the JSON body
```

### `POST /api/auth/google/exchange/`

**Request body:**
```json
{
    "code": "<authorization code from Google>",
    "code_verifier": "<PKCE verifier from sessionStorage>",
    "school_id": 1,                    // optional — attaches school to new registration requests
    "invitation_token": "abc123..."    // optional — invitation fast path
}
```

**Responses:**

| Status | Meaning |
|--------|---------|
| 200 | `{ access_token, refresh_token, user }` — user found/created and approved |
| 202 | `error_code: approval_pending` or `new_registration` — a `UserRegistrationRequest` exists or was just created; awaiting management approval |
| 400 | Missing `code`/`code_verifier`, Google exchange failed, or invalid/expired/mismatched invitation token |
| 403 | `error_code: approval_pending` (existing unapproved user) or `registration_rejected` |
| 504 | Google API timed out |

**User resolution order:** existing `User` by email → `ApprovedEmail` (create approved user) → `UserRegistrationRequest` (approved: create user; rejected: 403; pending: 202) → create new pending `UserRegistrationRequest` (202). School is always derived from request context or the approver's school — `School.objects.first()` is banned (SEC-05).

**Invitation fast path:** when `invitation_token` is passed, the token must be valid, unused, and match the Google account email; the user is created pre-approved and the token is marked used.

## Registration

`POST /api/auth/register/` creates a `UserRegistrationRequest` — no password is collected. Management approves the request; approved users complete setup via an invitation link. Required fields: `email`, `first_name`, `last_name`; `user_type` (`teacher` or `student`, default `teacher`) and `school_id` are optional. Returns 202 on success; 400/403 if the email already has an account, pre-approval, or an existing request.

## JWT Token Authentication

### Login
```
POST /api/auth/token/
{ "email": "user@example.com", "password": "..." }
```
Returns `{ access_token, refresh_token, user }`. Users with `is_approved=False` get 403 — the approval gate before JWT issuance is a locked security decision (LOCK-01). Users with only a pending/rejected registration request get a descriptive 403.

### Token Configuration
```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),  # 1 hour
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),     # 1 day
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
}
```

### Usage and refresh
```
Authorization: Bearer <access_token>

POST /api/auth/token/refresh/
{ "refresh": "<refresh_token>" }
→ { "access_token": "...", "refresh_token": "..." }
```

### Logout
```
POST /api/auth/logout/
{ "refresh": "<refresh_token>" }
```
Blacklists the refresh token. The access token remains valid until it expires (max 1 hour).

## Password Reset

1. `POST /api/auth/password-reset/` with `{ email }` — always returns a generic success message (does not reveal account existence); emails a link `{FRONTEND_URL}/reset-password?uid=...&token=...`
2. `POST /api/auth/password-reset/validate/` with `{ uid, token }` — returns `{ valid, email }` before showing the form
3. `POST /api/auth/password-reset/confirm/` with `{ uid, token, password, confirm_password }` — validates password strength and sets it

## Authorization System

### Permission Decorators (`custom_auth/decorators.py`)

```python
@role_required('teacher', 'management')   # any listed role
@teacher_required                          # teachers only
@management_required                       # management only
@teacher_or_management_required            # either
@owns_resource_or_management('teacher')    # own resource, or management
```

### Permission Logic

- **Authentication:** valid JWT required (401 otherwise)
- **Role:** user must hold one of the required roles (403 otherwise)
- **Approval:** management is auto-approved; teachers/students must be approved (403 while pending)
- **Ownership:** teachers/students access only their own resources; management accesses all — but always scoped to `request.user.school` (multi-tenant isolation, SEC-04)

## User Profile

```
GET /api/auth/user/
Authorization: Bearer <access_token>
```

Returns `user` with `email`, `name`, `user_id`, `user_type`, `is_approved`, `first_name`, `last_name`, `phone_number`, `address`, `bio`, `instruments`, `hourly_rate`.

## Configuration

```bash
# Google OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_API_TIMEOUT=10        # optional, seconds (default 10)

# Django
SECRET_KEY=...
# settings.FRONTEND_URL must match the SPA's OAuth redirect_uri
```

Required apps: `rest_framework_simplejwt`, `rest_framework_simplejwt.token_blacklist`, `custom_auth`. `AUTH_USER_MODEL = 'billing.User'`. django-allauth is **not** installed — do not add it back.

## Security — Locked Decisions

See `.planning/codebase/SECURITY.md` for the full list. The ones that live in this app:

- **LOCK-01:** the `is_approved` check before JWT issuance must never be removed
- **LOCK-02:** never use `School.objects.first()` to assign a school
- **LOCK-03:** both Google API calls in `google_exchange` must keep their `timeout=`
- **LOCK-04:** tokens are returned in the response body only — never in URL params or redirects
