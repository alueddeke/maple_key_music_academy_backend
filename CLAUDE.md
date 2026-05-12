# Backend CLAUDE.md

> Before working here, read `.planning/codebase/CONVENTIONS.md` and `.planning/codebase/ARCHITECTURE.md`.
> Architecture overview, domain models, and key design decisions are in those files — not here.

---

## Migration Workflow

Always merge `develop` before running `makemigrations`:

```bash
git checkout develop && git pull
git checkout feature/my-feature
git merge develop
docker compose exec api python manage.py makemigrations billing
# Check for duplicate numbers:
ls -1 billing/migrations/0*.py | cut -d_ -f1 | sort | uniq -d
```

Never run `makemigrations` on production. Migrations auto-run via GitHub Actions on push to `production`.

---

## Test Commands

```bash
docker compose exec api pytest tests/                     # full suite
docker compose exec api pytest tests/integration/         # integration only
docker compose exec api pytest tests/unit/                # unit only
docker compose exec api pytest tests/ -k "test_name"      # single test
```

---

## Django-Specific Gotchas

**Mutation parameter names:** Always read the mutation definition in the query hook before calling. Wrong parameter names fail silently. e.g. `updateContact({ id, data })` not `updateContact({ studentId, contactId, data })`.

**Form state with API data:** Initialize form values in a `useEffect` watching the data, not just `defaultValues` — data loads after render.

**Race condition on detail views:** Use a "pending edit" state pattern — set `pendingEdit`, then open dialog in a `useEffect` that watches `detailData && !loading`.

**Disabled vs read-only fields:** Use `<Input disabled />` not a `<div>` — keeps value in form state for calculations.

**Dynamic form validation:** Build schema in a function when fields are conditionally required: `const getSchema = (flag) => z.object({...})`.

**When deleting a view function:** Also remove from `billing/views/__init__.py` re-exports and `urls.py` in the same commit — or you'll get an `ImportError`.

**django-simple-history:** When removing model fields, verify the migration covers `HistoricalXXX` shadow tables in addition to the main table.

---

## CI Gate (Phase 8)

The `production` branch requires the "test" status check to pass before merging.

- **Job name:** `test` (in `.github/workflows/deploy.yml`)
- **What it does:** Runs `pytest tests/` with a PostgreSQL service container
- **Branch protection:** Configured manually in GitHub Settings → Branches → `production` rule

If branch protection is not yet configured, see `maple_key_music_academy_docker/CLAUDE.md → Branch Protection Setup`.
