# Teacher Invoice Submission Guide

## API Endpoint
`POST /api/billing/invoices/teacher/submit-lessons/`

## Authentication
Requires JWT token with `teacher` role.

## Request Format

```json
{
  "lessons": [
    {
      "student_name": "John Doe",           // Required
      "student_email": "john@example.com",  // Optional
      "duration": 1.5,                      // Optional (default: 1.0)
      "rate": 80.00,                        // Optional (default: teacher's hourly_rate)
      "scheduled_date": "2024-01-15T14:00:00Z",  // Optional (default: current time)
      "teacher_notes": "Worked on scales"   // Optional
    }
  ],
  "due_date": "2024-02-15T00:00:00Z",      // Optional (default: 30 days from now)
  "month": "January 2024"                   // Optional (for reference)
}
```

## Field Validation

### Required Fields
- `student_name` - Must be at least 2 characters

### Optional Fields
- `student_email` - If provided, will look up existing student or create new one
  - If omitted, creates student with temporary email: `{name}@temp.com`
  - If student already exists with that email, uses existing student record
- `duration` - Hours taught (max: 9999.99, typically 0.25 - 100)
- `rate` - Hourly rate (defaults to teacher's configured rate)
- `scheduled_date` - When the lesson occurred
- `teacher_notes` - Additional notes about the lesson

## Student Handling Logic

1. **With email provided:**
   - Searches for existing student by email
   - If found: uses existing student
   - If not found: creates new student with provided email

2. **Without email:**
   - Generates temporary email: `student.name@temp.com`
   - Searches for existing student with that temp email
   - If found: uses existing student
   - If not found: creates new student

This means you can submit multiple lessons for the same student (by name) and they'll be correctly associated!

## Success Response (201 Created)

```json
{
  "message": "Lessons submitted and invoice created successfully",
  "invoice": {
    "id": 1,
    "teacher_name": "Jane Teacher",
    "invoice_type": "teacher_payment",
    "payment_balance": "120.00",
    "status": "pending",
    "due_date": "2024-02-15T00:00:00Z",
    "created_at": "2024-01-15T10:00:00Z",
    "lessons": [1, 2]
  },
  "lessons_created": 2
}
```

## Error Responses

### 400 Bad Request - No Lessons Provided
```json
{
  "error": "No lessons provided"
}
```

### 500 Internal Server Error - Validation Failed
```json
{
  "error": "Failed to create invoice",
  "details": "numeric field overflow\nDETAIL:  A field with precision 4, scale 2 must round to an absolute value less than 10^2.\n"
}
```

**Common causes:**
- **Duration too large**: Entered hours > 9999.99
  - Frontend should validate duration is reasonable (typically 0.25-100)
- **Database constraint violation**: Data doesn't meet model requirements

## Frontend Error Handling

The frontend now provides user-friendly error messages:

| Backend Error | User sees |
|--------------|-----------|
| `numeric field overflow` | "Hours value is too large. Please enter a value less than 100 hours." |
| `duplicate key ... email` | "A student with email 'X' already exists. This lesson has been added to the existing student's record." |
| Generic constraint error | "A student with this information already exists in the system." |

## Recent Improvements (October 2025)

1. **Duplicate student handling**: Now reuses existing students instead of failing
2. **Optional scheduled_date**: No longer required, defaults to current time
3. **Increased duration limit**: From 99.99 to 9999.99 hours
4. **Better error logging**: Server logs include full traceback for debugging
5. **User-friendly errors**: Frontend displays helpful messages instead of raw database errors

## Testing

```bash
# Test with minimal data
curl -X POST https://api.maplekeymusic.com/api/billing/invoices/teacher/submit-lessons/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "lessons": [
      {
        "student_name": "Test Student",
        "duration": 1.0
      }
    ]
  }'

# Test with full data
curl -X POST https://api.maplekeymusic.com/api/billing/invoices/teacher/submit-lessons/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "lessons": [
      {
        "student_name": "John Doe",
        "student_email": "john@example.com",
        "duration": 1.5,
        "rate": 85.00,
        "scheduled_date": "2024-01-15T14:00:00Z",
        "teacher_notes": "Great progress on scales"
      }
    ],
    "due_date": "2024-02-15T00:00:00Z",
    "month": "January 2024"
  }'
```

## Workflow

1. Teacher fills out invoice form with student names and hours
2. Frontend validates input (name length, reasonable hours)
3. Frontend submits to API
4. Backend:
   - Creates or finds student records
   - Creates lesson records (marked as "completed")
   - Creates invoice (status: "pending")
   - Calculates total payment
5. Invoice awaits management approval
6. Once approved, payment can be processed
