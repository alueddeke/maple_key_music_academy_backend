# Teacher Invoice Submission API

## Endpoint
`POST /api/billing/invoices/teacher/submit-lessons/`

Implemented in `billing/views/teacher.py` (`submit_lessons_for_invoice`). Submits a list of lessons and, in one transaction, creates the `Lesson` records, a pending `teacher_payment` invoice, and one pending `student_billing` invoice per student.

## Authentication
Requires a JWT with the `teacher` role (`@teacher_required`).

## Request Format

```json
{
  "lessons": [
    {
      "student_name": "John Doe",                 // Required
      "student_email": "john@example.com",        // Optional — used for student lookup
      "duration": 1.5,                            // Optional (default: 1.0, hours)
      "lesson_type": "in_person",                 // Optional: "in_person" (default) or "online"
      "is_trial": false,                          // Optional — omit to auto-detect (see below)
      "scheduled_date": "2026-01-15T14:00:00Z",   // Optional (default: current time)
      "teacher_notes": "Worked on scales"         // Optional
    }
  ],
  "due_date": "2026-02-15T00:00:00Z"              // Optional (default: 14 days from now)
}
```

Rates are **not** accepted from the request. They are derived server-side from `SchoolSettings` for the teacher's school:

- `online`: `online_teacher_rate` / `online_student_rate`
- `in_person`: teacher's `hourly_rate` / `inperson_student_rate`
- Trial lessons: `student_rate` forced to `0.00` (teacher still paid)

**Trial detection:** if `is_trial` is present it is respected as-is. If omitted, the lesson is auto-marked trial when the student has no completed lessons yet.

## Student Handling

1. **With `student_email`:** `get_or_create` by email — reuses the existing student or creates a new one in the teacher's school (auto-approved).
2. **Without email:** a placeholder email `noemail_{uuid12}@maplekeymusic.internal` is generated, so same-name students never collide.
3. **Newly created students** get a placeholder primary `BillableContact` with `INCOMPLETE` fields. Management must complete it in Student Management before the invoice can move forward.

## Billing-Contact Validation (400)

Before anything is created, every **existing** student in the payload is validated:

- The student must have a primary `BillableContact`.
- All contact fields must be present and real: `first_name`, `last_name`, `email`, `phone`, `street_address`, `city`, `province`, `postal_code`. Blank values or placeholders (`INCOMPLETE`, `XX`, `N/A`, `TBD`) fail validation.

Brand-new students (created by this submission) skip validation — they get the placeholder contact instead.

If any student fails, the whole submission is rejected with **400** and nothing is created:

```json
{
  "error": "Cannot submit invoice - some students have incomplete billing information",
  "details": [
    {
      "student": "John Doe",
      "email": "john@example.com",
      "missing_fields": ["phone", "postal_code"],
      "incomplete_fields": ["province"],
      "error": "Incomplete billing contact. Missing: phone, postal_code | Incomplete: province. Please update student information in Student Management."
    }
  ],
  "message": "Please update student billing information in Student Management before submitting this invoice. All fields (name, email, phone, street address, city, province, postal code) are required."
}
```

A student with **no** billing contact at all appears in `details` with:

```json
{
  "student": "John Doe",
  "email": "john@example.com",
  "error": "No billing contact found. Please add complete billing information in Student Management."
}
```

## Success Response (201 Created)

```json
{
  "message": "Lessons submitted and invoice created successfully",
  "invoice": {
    "id": 1,
    "invoice_number": "INV-2026-01-0001",
    "invoice_type": "teacher_payment",
    "teacher_name": "Jane Teacher",
    "school_name": "Maple Key Music Academy",
    "payment_balance": "120.00",
    "total_amount": "120.00",
    "status": "pending",
    "due_date": "2026-02-15T00:00:00Z",
    "lessons": [1, 2]
  },
  "lessons_created": 2,
  "student_invoices_created": 1
}
```

`invoice` is the full `InvoiceSerializer` payload (all `Invoice` model fields plus `teacher_name`, `student_name`, `school_name`, `created_by_name`, `approved_by_name`). Lessons are created with status `completed`. One `student_billing` invoice (status `pending`, 14-day term) is also created per distinct student, totalled at `student_rate`.

## Other Error Responses

### 400 — No lessons provided
```json
{ "error": "No lessons provided" }
```

### 500 — Creation failed
```json
{
  "error": "Failed to create invoice",
  "details": "<exception message>"
}
```

Common cause: a numeric overflow from an unreasonable `duration` (the field allows up to 9999.99; the frontend should validate that hours are realistic). The server logs the full traceback.

## Testing

```bash
# Minimal
curl -X POST "https://api.maplekeymusic.com/api/billing/invoices/teacher/submit-lessons/" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "lessons": [
      { "student_name": "Test Student", "duration": 1.0 }
    ]
  }'

# Full
curl -X POST "https://api.maplekeymusic.com/api/billing/invoices/teacher/submit-lessons/" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "lessons": [
      {
        "student_name": "John Doe",
        "student_email": "john@example.com",
        "duration": 1.5,
        "lesson_type": "in_person",
        "scheduled_date": "2026-01-15T14:00:00Z",
        "teacher_notes": "Great progress on scales"
      }
    ],
    "due_date": "2026-02-15T00:00:00Z"
  }'
```

## Workflow

1. Teacher submits lesson details.
2. Backend validates billing contacts for all existing students (400 with per-student details on failure).
3. In one transaction: students found/created, `Lesson` records created (`completed`), teacher invoice created (`pending`), per-student billing invoices created (`pending`).
4. Teacher invoice awaits management approval via `POST /api/billing/invoices/teacher/{id}/approve/`.

> Note: the primary teacher payroll flow is now the monthly batch workflow (`MonthlyInvoiceBatch` — see `billing/README.md`). This endpoint is the direct lessons-to-invoice submission path.
