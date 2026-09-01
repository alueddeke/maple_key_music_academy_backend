# Billing App

The Billing app owns users, schools, lessons, schedules, and the entire monthly billing cycle — teacher payroll on one side, student pre-billing and credits on the other.

This is a tour of `billing/models.py` (~23 models). For system architecture and design decisions see `../../.planning/codebase/ARCHITECTURE.md`; for a plain-language walkthrough of the billing cycle and per-lesson money rules see `../../.planning/BILLING-PROCESS.md`.

## Model Groups

### Users & Schools

| Model | What it is |
|-------|------------|
| `School` | Tenant root. Tax rates, billing cycle day, contact info, and per-school Helcim credentials (blank = fall back to `HELCIM_*` env settings). |
| `SchoolSettings` | Per-school rates (`online_teacher_rate` 45, `online_student_rate` 60, `inperson_student_rate` 100 defaults) and the waived-cancellation limit policy (MAP-101). |
| `User` | Unified custom user (`AbstractUser`, email as username) with `user_type` = management / teacher / student. Teachers carry `hourly_rate` (default **50.00**); management is auto-approved on save. Every user has a `school` FK. |
| `BillableContact` | Parent/guardian billing contact for a student. One `is_primary` contact per student (enforced in `save()`); caches `helcim_customer_id` after first invoice send. |

### Lessons & Schedules

| Model | What it is |
|-------|------------|
| `Lesson` | A delivered/scheduled lesson with **dual rates**: `teacher_rate` (paid to teacher) and `student_rate` (billed to student), locked at creation from `SchoolSettings` / teacher `hourly_rate`. Statuses include `trial` (teacher paid, student pays $0), `waived`, `forfeited`. First-ever lesson for a student auto-marks as trial. |
| `RecurringLessonsSchedule` | Weekly teacher-student slot (day, time, duration, locked rates) with optional pause window for planned leave. `generate_lessons_for_month()` projects the dates without creating records. |

### Monthly Batch Flow (Teacher Payroll)

| Model | What it is |
|-------|------------|
| `MonthlyInvoiceBatch` | One teacher's month of lessons. `draft → submitted → approved → rejected`; unique per teacher/month/year. Locked once its teacher `Invoice` is generated; `archived_at` removes it from Payroll lists without deleting anything. |
| `BatchLessonItem` | A lesson line inside a batch (rates, status, notes). `calculate_teacher_payment()` / `calculate_student_charge()` encode the per-status money rules. |
| `BatchRejectionSnapshot` | Frozen JSON copy of the batch's items at each rejection — the audit record of what was actually rejected. |
| `StudentInvoice` | Per-student audit record created at batch approval (what the student was billed), with cached billing-contact data and credit-reconciliation fields. |
| `Invoice` | Classic invoice with `invoice_type` = `teacher_payment` or `student_billing`. The teacher-payment invoice is generated at month-end from an approved batch; carries approval/rejection tracking and payroll fields (`date_paid`, `reference_number`). |

### Student Pre-Billing & Credits

| Model | What it is |
|-------|------------|
| `PreBillingInvoice` | The invoice actually sent to the parent for an upcoming period. `draft → sending → sent → adjusted → paid`; amount locked at draft generation; unique per student/school/period. Stores Helcim invoice id/number and hosted-payment token (no card data). |
| `StudentCreditAccount` | Per-student credit wallet. `balance >= 0` enforced by DB check constraint — no debt tracking. |
| `CreditTransaction` | Immutable ledger entry. Amount is **always positive**; the `type` implies direction: `pre_billing_payment` (+), `waived_rollover` (+), `forfeited` (−/audit). |

### Helcim Integration

| Model | What it is |
|-------|------------|
| `HelcimWebhookEvent` | One payment-webhook receipt. `helcim_transaction_id` is the idempotency key (unique) so Helcim retries are no-ops. `processing_status` tracks reconciliation outcome (`credited`, `not_approved`, retryable states, ...). |

Helcim API client and webhook reconciliation live in `billing/services/` (`helcim_client.py`, `webhook_processing.py`).

### Registration & Invitations

| Model | What it is |
|-------|------------|
| `ApprovedEmail` | Pre-approved email that can register without review. |
| `UserRegistrationRequest` | Registration request pending management approval (`pending / approved / rejected`). |
| `InvitationToken` | Single-use, expiring token for invited users to set up their account. |

### Settings & Misc

| Model | What it is |
|-------|------------|
| `GlobalRateSettings` | Legacy singleton rate settings — fallback when `SchoolSettings` is unavailable. |
| `InvoiceRecipientEmail` | Per-school list of emails that receive invoice PDFs on teacher submission. |
| `SchoolMonthlyExpenses` / `SchoolExpenseItem` | Monthly operating expenses per school, shown on the billing dashboard (Phase 21). |

## Key Flows

### Teacher batch: submit → approve → month-end

1. Teacher opens their month — `MonthlyInvoiceBatch` is get-or-created and `BatchLessonItem` rows are synced from active recurring schedules (manual one-offs can be added).
2. Teacher marks statuses and **submits**. Management **approves** (charges each student's credit wallet, creates `StudentInvoice` records) or **rejects** (snapshot taken, batch back to draft).
3. Approved-but-uninvoiced batches are the teacher's adjustment window: they can mark exceptions (waived/forfeited/etc.) via the adjustments endpoint.
4. Management **generates the teacher Invoice** from the Month-End queue — pays the teacher, writes credit rollovers, and locks the batch. Then mark-as-paid and archive.

### Pre-billing: generate → send → webhook credit

1. Management generates a `PreBillingInvoice` draft per student for the upcoming period (projected lesson cost minus existing credit, floored at $0; duplicate generation blocked by the DB constraint).
2. Send creates the Helcim invoice and emails the parent a hosted-payment link.
3. Parent pays → Helcim webhook arrives → `HelcimWebhookEvent` stored idempotently → reconciliation credits the `StudentCreditAccount`, records a `CreditTransaction`, and marks the invoice `paid`.

## Views & Endpoints

Views are split by audience in `billing/views/`: `teacher.py` (batches, adjustments, paystubs, legacy submit-lessons), `management.py` (approval, payroll, school-scoped admin), `pre_billing.py`, `webhooks.py`, `students.py`, `lessons.py`, `invitation.py`. All management querysets filter by `school=request.user.school` — see `../../.planning/codebase/SECURITY.md` (LOCK-05) before touching them.

For the teacher submit-lessons endpoint specifically, see `../INVOICE_SUBMISSION_GUIDE.md`.

## Django Admin

Role-based User admin, lesson/invoice/batch admins with status filtering. Access at `http://localhost:8000/admin/`.

## Testing

```bash
docker compose exec api pytest tests/                # full suite
docker compose exec api pytest tests/integration/    # integration only
```

See `.planning/codebase/TESTING.md` for structure.
