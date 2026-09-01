# Maple Key Music Academy — Backend

**Start here** (human or AI — this file is the universal entry point for this repo).

Django/DRF API running a real Toronto music school's money cycle: recurring
lesson schedules feed teacher batch submissions; approval atomically creates
lessons and debits student credit wallets; pre-billing invoices go out through
Helcim (Canadian payment processor) with HMAC-verified, idempotent webhook
reconciliation. It handles real money in production today.

## The domain in one tree

Everything depends on what's above it — you can't touch a lower layer safely
without understanding the ones it feeds:

```
users (management / teacher / student, one User model, role field)
  → recurring schedules (teacher×student, day/time/rate)
    → monthly teacher batches (prepopulated from schedules; teacher marks
      cancellations/exceptions, submits; management approves or rejects)
      → lessons (created AT APPROVAL, atomically, with wallet debits)
      → credit wallet (per student; waives/refunds land here)
        → pre-billing invoices (bill-ahead drafts projected from schedules)
          → send runs (bulk send = queued snapshot drained by a worker container)
            → Helcim invoice + hosted payment page + our email
              → webhook reconciliation (HMAC-verified, idempotent, credits wallet)
  → teacher payroll (approved batches → month-end teacher invoices, mark-as-paid)
```

Closed vocabulary that matters: **lesson vs batch-item vs invoice vs credit**;
**waived vs forfeited vs cancelled** (each has a different money rule: waived
charges nobody, forfeited charges the student, both pay the teacher nothing).

## User paths (what the API actually serves)

- **Teacher:** log in → Monthly Invoices → review the prepopulated month →
  add/edit/reschedule/cancel lessons → submit batch → (after approval) mark
  exceptions until the invoice generates → see paystub.
- **Management:** review/approve/reject batches → Student Billing: generate
  bill-ahead drafts → Send All (queues a send run; worker sends) → Month End:
  generate teacher invoices → "Have you paid?" → dashboards.
- **Parent:** gets an email with a Helcim payment link — never logs in.
  Payment → webhook → wallet credit → next invoice nets it off.

## Layout

```
billing/            almost everything: models, views/ (function-based), services/,
                    management/commands/ (seed_realistic, bootstrap_dev,
                    process_invoice_send_runs = the send-run worker, ...)
custom_auth/        JWT + Google OAuth (PKCE), decorators (@management_required,
                    @teacher_required), registration guards, throttling
teacher_profiles/   instruments, availability
notifications/      in-app bell
analytics/          dashboard aggregation
tests/              pytest — unit/ + integration/
```

## Run it

Dev runs through the docker repo (sibling `maple_key_music_academy_docker/`):

```bash
cd ../maple_key_music_academy_docker && make up
# first boot auto-seeds a demo school; sign in at http://localhost:5173
#   e2e.manager@maplekeytest.com / testpass123
# make up-empty boots with no data
```

Tests: `docker compose exec api pytest tests/` (600+; run before any commit).

## Hard rules (violating these has broken production before)

- **Money is `Decimal`, never float.** Rates lock at creation.
- **No Helcim HTTP call inside `transaction.atomic()`** — rollback orphans a
  real Helcim invoice. Claim state with a conditional UPDATE, call outside,
  write results in a minimal transaction.
- **Every queryset filters by `request.user.school`** (multi-school isolation).
- **Idempotency everywhere money moves:** webhook events are replay-safe;
  invoice sends claim `draft→sending` so exactly one sender wins.
- Function-based views + decorators only; no ViewSets.
- Branches: `develop` → `production` (PR-gated, migrations auto-run behind a
  pg_dump). Never push production directly.
- Migration workflow: merge develop before `makemigrations`; check duplicate
  numbers: `ls -1 billing/migrations/0*.py | cut -d_ -f1 | sort | uniq -d`

## Where deeper docs live

- `docs/USER_GUIDE.md` — full billing workflow narrative
- `billing/README.md`, `custom_auth/README.md` — app-level detail
- Umbrella/planning repo (local): `.planning/codebase/` — ARCHITECTURE,
  CONVENTIONS, STANDARDS, SECURITY (authoritative for agents working the
  full workspace)
- `CLAUDE.md` — repo-specific gotchas for Claude sessions
