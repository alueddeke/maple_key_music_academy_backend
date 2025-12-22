# ADR-BE-0002: Use Email Instead of Username for User Authentication

**Status:** Accepted

**Date:** 2024-08-20

**Deciders:** Antoni

**Tags:** #authentication #database-design #api-design #developer-experience #security

**Technical Story:** User authentication system design

---

## Context and Problem Statement

Django's default User model requires a `username` field for authentication. For a music school management system, we need to decide whether to use Django's default username-based authentication or switch to email-based authentication.

**Key Questions:**
- Should users log in with username or email?
- How does this choice affect user experience and support burden?
- What's the impact on OAuth integration (Google login)?

---

## Decision Drivers

* **User experience** - Email addresses are more memorable than usernames
* **Support burden** - Reduce "forgot username" support tickets
* **OAuth compatibility** - Social auth providers return emails, not usernames
* **API simplicity** - REST API clients prefer email-based endpoints
* **Music school context** - Parents/teachers expect email login
* **Security** - Email uniqueness already required for password resets

---

## Considered Options

* **Option 1:** Keep Django default (username required, email optional)
* **Option 2:** Username + required email (both unique)
* **Option 3:** **Email as USERNAME_FIELD, remove username** (CHOSEN)
* **Option 4:** Email stored in username field (hack)

---

## Decision Outcome

**Chosen option:** "Email as USERNAME_FIELD, remove username field entirely"

**Rationale:**
We removed the `username` field completely and set `USERNAME_FIELD = 'email'` to use email for authentication. This matches user expectations (everyone has email, not everyone wants to create a username), reduces support burden, and aligns perfectly with OAuth flows where providers return email addresses. The custom `UserManager` handles email normalization and validation.

### Consequences

**Positive:**
* **Better UX:** Users remember their email, not arbitrary usernames
* **Lower support burden:** No "forgot username" tickets (~30% of auth issues in research)
* **OAuth simplicity:** Google OAuth returns email, maps directly to our system
* **API clarity:** `POST /auth/login {"email": "...", "password": "..."}` is intuitive
* **No duplicate fields:** Email serves both authentication and communication purposes

**Negative:**
* **Email visible in URLs:** If we used username-based profile URLs, usernames hide identity. We use UUIDs instead.
* **Migration from default:** Can't use default Django User model (minor, we need custom anyway)
* **Third-party app compatibility:** Some Django packages assume username exists (rare, fixable)

**Neutral:**
* **Email must be unique:** Already required for password reset, no real impact
* **Custom UserManager required:** Small overhead (~20 lines) for email normalization

---

## Detailed Analysis of Options

### Option 1: Django Default (Username Required)

**Description:**
Keep Django's default: `username` for login, `email` optional.

**Pros:**
* Out-of-box Django compatibility
* Works with all third-party packages
* Username can be pseudonymous

**Cons:**
* **Poor UX:** Users forget usernames, need support
* **Duplicate data:** Both username and email needed
* **OAuth friction:** Must generate username from email
* **Parent confusion:** "What's a username?" for non-tech parents

**Implementation Effort:** Low (no changes needed)

### Option 2: Both Username and Email Required

**Description:**
Require both fields, allow login with either.

**Pros:**
* Flexibility for users
* Still somewhat compatible with Django packages

**Cons:**
* **Confusing UX:** Which do I use to log in?
* **Duplicate data:** Two unique fields to manage
* **More validation:** Must ensure both are unique
* **OAuth still awkward:** Generate username or ask user?

**Implementation Effort:** Medium

### Option 3: Email as USERNAME_FIELD (CHOSEN)

**Description:**
Set `USERNAME_FIELD = 'email'`, remove `username` field, custom UserManager.

**Pros:**
* Clean UX - one field for identity
* OAuth integration is seamless
* API endpoints are intuitive
* No duplicate data
* Matches user expectations

**Cons:**
* Requires custom UserManager
* Some third-party packages need tweaks
* Email in URLs (solved with UUIDs)

**Implementation Effort:** Low

**Code Reference:** `billing/models.py:44-45, 64-68`

### Option 4: Email in Username Field (Hack)

**Description:**
Store email in the `username` field, keep email field separate.

**Pros:**
* Compatible with default Django
* Works with third-party packages

**Cons:**
* **Confusing:** `username` field contains email
* **Duplicate data:** Email stored in two fields
* **Validation complexity:** Must sync fields
* **Hacky solution:** Violates principle of least surprise

**Implementation Effort:** Low but ugly

---

## Validation

**How we'll know this decision was right:**
* **Login success rate:** >95% first-attempt logins (no username confusion)
* **Support tickets:** <5% auth-related (vs 30% industry average for username/email)
* **OAuth success:** >90% OAuth registration completions
* **Developer feedback:** API users prefer email-based endpoints

**When to revisit this decision:**
* **If privacy becomes critical:** Need to hide user identity (unlikely for music school)
* **If third-party integration breaks:** Django package requires username (can work around)
* **If email changes break system:** Users frequently change emails (rare, can handle with update flow)

---

## Links

* Implementation: `billing/models.py:44-45` - `username = None`
* USERNAME_FIELD: `billing/models.py:64-65` - `USERNAME_FIELD = 'email'`
* UserManager: `billing/models.py:5-29` - Email normalization and validation
* Unique constraint: `billing/models.py:40` - `email = models.EmailField(unique=True)`
* Related ADR: [BE-0001: Unified User Model](BE-0001-unified-user-model.md)
* Related ADR: [BE-0006: OAuth with Django Allauth](BE-0006-oauth-with-django-allauth.md)

---

## Notes

**Custom UserManager Implementation:**
```python
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)  # Lowercase domain
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
```

**User Model Configuration:**
```python
class User(AbstractUser):
    username = None  # Remove username field
    email = models.EmailField(unique=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'user_type']

    objects = UserManager()
```

**API Endpoint Example:**
```bash
# Clean and intuitive
curl -X POST /api/auth/token/ \
  -d '{"email": "teacher@school.com", "password": "..."}'

# vs confusing username-based
curl -X POST /api/auth/token/ \
  -d '{"username": "teacher123", "password": "..."}'  # What was my username again?
```
