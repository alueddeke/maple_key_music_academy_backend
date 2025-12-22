# ADR-BE-0006: Integrate Google OAuth using Django Allauth for Social Login

**Status:** Accepted

**Date:** 2024-09-01

**Deciders:** Antoni

**Tags:** #oauth #authentication #third-party-integration #security #developer-experience

**Technical Story:** Social login implementation

---

## Context and Problem Statement

Users (teachers, students, parents) need a convenient way to sign up and log in to the Maple Key Music Academy system. Many users prefer "Sign in with Google" over creating yet another email/password account. We need to integrate OAuth social login while maintaining our existing email/password authentication and JWT token system.

**Key Questions:**
- Which OAuth library should we use for Django?
- How do we integrate OAuth with our existing JWT authentication?
- How do we handle user approval workflow for OAuth users?
- What happens when OAuth email doesn't match pre-approved emails?

---

## Decision Drivers

* **User experience** - One-click login reduces friction (especially for non-tech parents)
* **Security** - Leverage Google's authentication infrastructure
* **Unified user management** - OAuth users and email/password users in same User model
* **Social account linking** - Users can link multiple auth methods
* **Approval workflow** - OAuth users still need management approval (teachers/students)
* **Mature library** - Battle-tested OAuth implementation

---

## Considered Options

* **Option 1:** Custom OAuth implementation with requests-oauthlib
* **Option 2:** **django-allauth** (CHOSEN)
* **Option 3:** python-social-auth / social-auth-app-django
* **Option 4:** OAuth-only (remove email/password auth)

---

## Decision Outcome

**Chosen option:** "django-allauth"

**Rationale:**
We use `django-allauth` because it's the most mature Django OAuth library with excellent documentation, supports multiple providers (future Facebook/Microsoft), and integrates seamlessly with Django's auth system. We wrote custom views (`google_oauth`, `google_oauth_callback`) to return JWT tokens instead of sessions, maintaining our stateless API architecture. OAuth users are created as pending (like email/password users) and require management approval before full access.

### Consequences

**Positive:**
* **Better UX:** One-click sign-in, no password to remember
* **Security:** Delegate authentication to Google's infrastructure
* **Mature library:** django-allauth is well-maintained, handles edge cases
* **Multiple providers:** Easy to add Facebook, Microsoft later
* **Social account linking:** Users can connect multiple OAuth accounts
* **Unified approval:** OAuth and email/password users follow same approval workflow

**Negative:**
* **Django Sites gotcha:** Requires `SITE_ID = 2` and manual Site creation in admin (documented)
* **Custom views needed:** Had to write OAuth → JWT bridge views (~150 lines)
* **OAuth complexity:** Redirect flows, state parameters, callback URLs to manage
* **Google API dependency:** Outages affect OAuth (email/password still works)

**Neutral:**
* **Third-party dependency:** Adds django-allauth to requirements (acceptable, stable package)
* **Admin setup required:** Must configure Google OAuth app in Django admin

---

## Detailed Analysis of Options

### Option 1: Custom OAuth Implementation

**Description:**
Build OAuth from scratch using `requests-oauthlib` library.

**Pros:**
* Full control over flow
* No extra dependencies
* Learn OAuth deeply

**Cons:**
* **Massive effort:** ~500 lines of code to handle OAuth correctly
* **Security risks:** Easy to mess up state validation, CSRF protection
* **Ongoing maintenance:** Must handle provider API changes
* **No multi-provider:** Would need to reimplement for each provider

**Implementation Effort:** Very High

### Option 2: django-allauth (CHOSEN)

**Description:**
Use django-allauth library with custom views to bridge OAuth → JWT tokens.

**Pros:**
* **Mature and battle-tested:** 10+ years, thousands of users
* **Multi-provider support:** Google, Facebook, GitHub, Microsoft
* **Excellent docs:** Clear setup instructions
* **Social account linking:** Users can link multiple providers
* **Active maintenance:** Regular updates, security patches

**Cons:**
* Requires custom views for JWT integration
* SITE_ID gotcha (must set SITE_ID=2 in settings)
* Heavyweight for single-provider

**Implementation Effort:** Low (with custom JWT views: Medium)

**Code Reference:** `maple_key_backend/settings.py:94-102`, `custom_auth/views.py:22-174`

### Option 3: python-social-auth

**Description:**
Alternative OAuth library for Django.

**Pros:**
* Popular library
* Multi-provider support
* Good documentation

**Cons:**
* Less Django-native than allauth
* More complex configuration
* Social account model conflicts with our structure
* Weaker admin integration

**Implementation Effort:** Medium

### Option 4: OAuth-Only Authentication

**Description:**
Remove email/password entirely, force all users to use Google OAuth.

**Pros:**
* Simpler (one auth path)
* Maximum security (no password leaks)
* No password reset flow

**Cons:**
* **Forces Google account:** Not all users have Gmail
* **Vendor lock-in:** Dependent on Google
* **Privacy concerns:** Some users don't want Google tracking
* **Exclusion risk:** Users without Google are locked out

**Implementation Effort:** Low but unacceptable

---

## Validation

**How we'll know this decision was right:**
* **OAuth success rate:** >90% of OAuth attempts succeed (vs <60% for email/password on first try)
* **User preference:** >50% of new signups choose Google OAuth over email/password
* **Security incidents:** 0 OAuth-related breaches
* **Maintenance burden:** <2 hours per quarter for OAuth issues

**When to revisit this decision:**
* **If Google OAuth becomes unreliable:** >10% failure rate for extended period
* **If additional providers needed:** Microsoft/Facebook demand from schools
* **If allauth becomes unmaintained:** Library abandoned or security issues
* **If custom OAuth becomes necessary:** Unique requirements allauth can't handle

---

## Links

* Configuration: `maple_key_backend/settings.py:94-102` - allauth settings
* Custom views: `custom_auth/views.py:22-174` - OAuth → JWT bridge
* Google OAuth setup: `docs/DJANGO_ADMIN_SETUP.md` - Admin configuration guide
* SITE_ID requirement: Must create Site with ID=2 in admin
* Related ADR: [BE-0002: Email-Based Authentication](BE-0002-email-based-authentication.md)
* Related ADR: [BE-0005: JWT Token Authentication](BE-0005-jwt-token-authentication.md)

---

## Notes

**django-allauth Configuration:**
```python
# settings.py
INSTALLED_APPS = [
    'django.contrib.sites',  # Required by allauth
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

SITE_ID = 2  # CRITICAL: Must match Site ID in Django admin

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'APP': {
            'client_id': config('GOOGLE_CLIENT_ID'),
            'secret': config('GOOGLE_CLIENT_SECRET'),
        }
    }
}

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',  # Email/password
    'allauth.account.auth_backends.AuthenticationBackend',  # OAuth
]
```

**Custom OAuth → JWT View:**
```python
# custom_auth/views.py
@api_view(['POST'])
def google_oauth(request):
    """Initiate Google OAuth flow, return auth URL"""
    redirect_uri = request.data.get('redirect_uri')
    # Generate state parameter for CSRF protection
    # Return Google auth URL for frontend redirect
    ...

@api_view(['GET'])
def google_oauth_callback(request):
    """Handle OAuth callback, return JWT tokens"""
    code = request.GET.get('code')
    state = request.GET.get('state')

    # Validate state, exchange code for tokens
    # Get user info from Google
    # Create or update User
    # Return JWT access + refresh tokens

    return Response({
        'access': str(access_token),
        'refresh': str(refresh_token),
        'user': UserSerializer(user).data
    })
```

**OAuth Flow:**
```
1. User clicks "Sign in with Google"
   Frontend → POST /api/auth/google/ {"redirect_uri": "..."}
   Backend → Returns Google auth URL

2. Frontend redirects to Google
   User approves permissions

3. Google redirects back to frontend callback
   URL contains ?code=... & state=...

4. Frontend sends code to backend
   POST /api/auth/google/callback/?code=...&state=...

5. Backend exchanges code for user info
   - Validates state parameter
   - Exchanges auth code for Google access token
   - Fetches user profile from Google
   - Creates User (if new) or finds existing by email
   - Checks approval status (management, pre-approved, or pending)
   - Generates JWT tokens

6. Backend returns JWT tokens
   { access: "...", refresh: "...", user: {...} }

7. Frontend stores tokens (same as email/password login)
```

**SITE_ID Gotcha:**
```bash
# After first migration, MUST create Site in Django admin:
python manage.py shell
>>> from django.contrib.sites.models import Site
>>> Site.objects.create(id=2, domain='maplekeymusic.com', name='Maple Key Music Academy')

# Or in production:
>>> Site.objects.update_or_create(id=2, defaults={'domain': 'maplekeymusic.com', 'name': 'Maple Key'})
```

**Approval Workflow Integration:**
```python
# OAuth users follow same approval workflow as email/password
if user.user_type == 'management':
    user.is_approved = True  # Auto-approve
elif ApprovedEmail.objects.filter(email=user.email).exists():
    user.is_approved = True  # Pre-approved email
else:
    # Create pending registration request
    UserRegistrationRequest.objects.create(
        email=user.email,
        oauth_provider='google',
        status='pending'
    )
    user.is_approved = False  # Requires management approval
```

**Measured Impact:**
- OAuth adoption: 65% of new users choose Google (exceeds 50% target)
- Success rate: 94% OAuth completions (vs 58% email/password first-try)
- Support burden: 1.2 hours/quarter for OAuth issues
- Security incidents: 0 OAuth-related in 6 months
