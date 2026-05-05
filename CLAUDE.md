# Backend CLAUDE.md

Detailed reference for `maple_key_music_academy_backend/`. Read this before editing models, serializers, views, migrations, or tests.

---

## Migration Workflow — CRITICAL

**The #1 source of deployment failures is duplicate migration numbers. Follow this exactly.**

### Before any migration work

```bash
# 1. Merge latest develop into your feature branch first
git checkout develop && git pull origin develop
git checkout feature/my-feature
git merge develop  # ← CRITICAL: gets latest migration numbers

# 2. Make your model changes, then generate
docker compose exec api python manage.py makemigrations billing

# 3. Check for duplicate numbers (if this prints anything, you have conflicts)
ls -1 maple_key_music_academy_backend/billing/migrations/0*.py | cut -d_ -f1 | sort | uniq -d
```

### Never do on production

```bash
# ❌ NEVER
docker exec maple-key-backend python manage.py makemigrations
```

Migrations are created locally, committed, and auto-applied by GitHub Actions on deploy. Production runs `migrate` only, never `makemigrations`.

### "column already exists" error

```bash
# Development — fresh database
docker compose down -v
docker compose up -d

# Production — restore from pre-deployment backup (see docker CLAUDE.md)
```

### Migration verification

GitHub Actions runs `showmigrations` after `migrate` and aborts if any show `[ ]`. If deployment fails here, check for unapplied or conflicting migrations locally and fix before re-deploying.

---

## Test Policy

**Tests are required for new features — not optional.**

### What requires a test

- New API endpoint → integration test in `tests/integration/`
- New model method or business logic → unit test in `tests/unit/`
- New React component → component test in `src/*/__tests__/`
- Changed business logic → update existing tests

### Running tests

```bash
# All backend tests
docker compose exec api pytest tests/

# Single file
docker compose exec api pytest tests/integration/billing/test_invoices.py

# With coverage
docker compose exec api pytest tests/ --cov=billing --cov-report=term-missing
```

### Test structure

```
tests/
├── unit/billing/         # Model methods, calculations, utilities
└── integration/billing/  # API endpoints, database operations
```

**Current coverage:** 31% overall, 83% billing models.

### Test before declaring complete

Always run `pytest tests/` before marking a task done. If you changed a model or view, run the relevant integration tests at minimum.

---

## Requirements.txt / Container Rebuild

Changes to `requirements.txt` **do not auto-apply** in the running container.

```bash
# Development shortcut (no rebuild needed)
docker compose exec api pip install -r requirements.txt

# Or full rebuild
docker compose build api
docker compose up -d api
```

Production: container rebuilds automatically via GitHub Actions on deploy.

---

## Django-Specific Patterns

### Site ID for Google OAuth

Uses `SITE_ID = 2` for Django Allauth. After first migration on a new environment, create the Site with ID=2 in Django admin (`/admin/sites/site/`). Without this, Google OAuth will fail silently.

### User model location

`AUTH_USER_MODEL = 'billing.User'` — the User model lives in the `billing` app, not `custom_auth`. Always import from there:

```python
from billing.models import User
# or
from django.contrib.auth import get_user_model
User = get_user_model()
```

### Email as username

`USERNAME_FIELD = 'email'` — never pass `username` to user creation. Use `email` everywhere.

### Singleton pattern — GlobalRateSettings

`GlobalRateSettings` is a singleton. Use `GlobalRateSettings.get_solo()` to fetch, never `.objects.first()` — that can return `None` if not yet created.

### Role-based view decorators

- `@management_required` — management users only
- `@teacher_required` — teacher users only
- Applied at the view level in `billing/views.py`

### Atomic invoice submission

`/api/billing/invoices/teacher/submit-lessons/` creates both lessons AND the invoice in one atomic transaction. If any lesson is invalid, nothing is saved. Don't split this into two calls.

---

## API Endpoints Reference

**Authentication:**
- `POST /api/auth/token/` — JWT tokens (email + password)
- `GET /api/auth/google/` — initiate Google OAuth
- `GET /api/auth/user/` — current user profile

**User Approval (management only):**
- `GET/POST /api/billing/management/registration-requests/`
- `GET/POST /api/billing/management/approved-emails/`
- `GET /api/billing/management/users/`

**Student Management (management only):**
- `GET/POST /api/billing/management/students/`
- `POST /api/billing/management/students/{id}/assign-teacher/`
- `GET/POST /api/billing/management/students/{id}/billable-contacts/`

**Rate Management (management only):**
- `GET/PUT /api/billing/management/global-rates/`
- `GET /api/billing/management/teachers/`
- `GET/PUT /api/billing/management/teachers/{id}/`

**Lessons:**
- `GET /api/billing/lessons/`
- `POST /api/billing/lessons/request/`
- `POST /api/billing/lessons/{id}/confirm/`
- `POST /api/billing/lessons/{id}/complete/`

**Invoices:**
- `POST /api/billing/invoices/teacher/submit-lessons/` — atomic: creates lessons + invoice
- `POST /api/billing/invoices/teacher/{id}/approve/`
- `GET /api/billing/invoices/teacher/{id}/pdf/`
- `GET /api/billing/teacher/batches/{id}/paystub/` — teacher paystub PDF

---

## Common Backend Errors

### `RelatedObjectDoesNotExist` on BillableContact

Each student must have exactly one primary BillableContact. If you see this on invoice submission, a student was created without one (auto-created students get a placeholder marked "INCOMPLETE"). Management must complete it via Student Management before approving.

### `IntegrityError: duplicate key` on migrations

You have a migration conflict — two files with the same number. Run the duplicate-check command above, delete the conflicting file, and regenerate.

### `SITE_MATCHING_QUERY_DOES_NOT_EXIST` on OAuth

Site ID=2 doesn't exist in the database. Go to `/admin/sites/site/` and create it, or run: `python manage.py shell -c "from django.contrib.sites.models import Site; Site.objects.get_or_create(id=2, defaults={'domain':'localhost', 'name':'localhost'})"`
