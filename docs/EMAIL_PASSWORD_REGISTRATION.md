# Email/Password Registration Flow

This document describes the email/password registration request flow for teacher and student accounts.

## Overview

The email/password registration flow follows the same approval pattern as OAuth registration, ensuring consistent user management regardless of authentication method.

## Registration Flow

### Step 1: User Registration

**Endpoint:** `POST /api/auth/register/`

**Request Body:**
```json
{
  "email": "teacher@example.com",
  "password": "SecurePassword123!",
  "first_name": "John",
  "last_name": "Doe",
  "user_type": "teacher"  // or "student"
}
```

**Validation:**
- Email must be in `ALLOWED_EMAILS` environment variable
- Password must meet Django's password validation requirements
- User type must be either "teacher" or "student"
- Email must not already be registered

**Response Scenarios:**

1. **Email is pre-approved (in `ApprovedEmail` table):**
   - Status: `201 Created`
   - User account created immediately with `is_approved=True`
   - Returns JWT tokens for immediate login
   ```json
   {
     "message": "Account created successfully",
     "user": { ... },
     "access_token": "...",
     "refresh_token": "..."
   }
   ```

2. **Email not pre-approved:**
   - Status: `202 Accepted`
   - Creates `UserRegistrationRequest` with `status='pending'`
   - Stores hashed password securely in notes field
   - User cannot login until approved
   ```json
   {
     "message": "Registration request submitted successfully",
     "details": "Your request is pending management approval...",
     "email": "teacher@example.com"
   }
   ```

3. **Email not in ALLOWED_EMAILS:**
   - Status: `403 Forbidden`
   - Registration blocked
   ```json
   {
     "error": "Email not authorized",
     "message": "Your email is not in the authorized list..."
   }
   ```

### Step 2: User Attempts Login (Before Approval)

**Endpoint:** `POST /api/auth/token/`

**Request Body:**
```json
{
  "email": "teacher@example.com",
  "password": "SecurePassword123!"
}
```

**Response:**
- Status: `403 Forbidden`
```json
{
  "error": "Approval pending",
  "message": "Your registration is pending management approval..."
}
```

### Step 3: Management Reviews and Approves

**Endpoint (List):** `GET /api/billing/management/registration-requests/?status=pending`

**Authentication:** Requires management user JWT token

**Response:**
```json
[
  {
    "id": 1,
    "email": "teacher@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "user_type": "teacher",
    "status": "pending",
    "requested_at": "2024-01-15T10:00:00Z",
    "notes": "HASHED_PASSWORD:pbkdf2_sha256$..."
  }
]
```

**Endpoint (Approve):** `POST /api/billing/management/registration-requests/{id}/approve/`

**Request Body (optional):**
```json
{
  "notes": "Approved - verified teacher credentials"
}
```

**Response:**
```json
{
  "message": "Registration request approved",
  "email": "teacher@example.com",
  "user_type": "teacher"
}
```

**What Happens:**
- Registration request status changes to `approved`
- Hashed password is preserved in notes field
- Management notes are appended (if provided)
- User can now login

### Step 4: User Logs In After Approval

**Endpoint:** `POST /api/auth/token/`

**Request Body:**
```json
{
  "email": "teacher@example.com",
  "password": "SecurePassword123!"
}
```

**Response:**
- Status: `200 OK`
- User account is created automatically on first login
- Returns JWT tokens
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "user": {
    "email": "teacher@example.com",
    "name": "John Doe",
    "user_id": 42,
    "user_type": "teacher",
    "is_approved": true
  }
}
```

## Technical Implementation Details

### Password Security

- Passwords are hashed using Django's `set_password()` method (PBKDF2)
- Hashed passwords are temporarily stored in `UserRegistrationRequest.notes` field
- Format: `HASHED_PASSWORD:pbkdf2_sha256$...`
- When management approves, the hashed password is preserved
- On first login, user account is created with the stored hash

### Approval Workflow

The approval logic preserves the hashed password when adding management notes:

```python
if reg_request.notes and reg_request.notes.startswith('HASHED_PASSWORD:'):
    # Keep the hashed password and append management notes
    if management_notes:
        reg_request.notes = f"{reg_request.notes}\nMANAGEMENT_NOTES: {management_notes}"
```

### Account Creation on First Login

When an approved user logs in for the first time:
1. System checks if user exists → No
2. Finds approved `UserRegistrationRequest`
3. Extracts hashed password from notes
4. Creates user account with stored hash
5. Authenticates user with provided password
6. Returns JWT tokens

## Comparison with OAuth Flow

| Aspect | Email/Password | OAuth (Google) |
|--------|---------------|----------------|
| Registration | Manual form | Google authentication |
| Password Storage | Hashed in registration request | No password needed |
| First Login | Creates account from request | Creates account immediately |
| Approval Check | Same | Same |
| User Experience | Traditional | Seamless (no password) |

## Environment Requirements

### Backend `.env` Configuration

```bash
# Email whitelist - Required for all authentication
ALLOWED_EMAILS=user1@example.com,user2@example.com,user3@example.com
```

## Frontend Integration

### Registration Form

```typescript
// POST /api/auth/register/
const response = await axios.post('/api/auth/register/', {
  email: 'teacher@example.com',
  password: 'SecurePassword123!',
  first_name: 'John',
  last_name: 'Doe',
  user_type: 'teacher'
});

// Handle responses:
if (response.status === 201) {
  // Pre-approved - got tokens, redirect to dashboard
  localStorage.setItem('access_token', response.data.access_token);
  router.push('/dashboard');
} else if (response.status === 202) {
  // Pending approval - show message
  showMessage('Registration submitted. Awaiting approval.');
  router.push('/pending-approval');
}
```

### Login Form

```typescript
// POST /api/auth/token/
const response = await axios.post('/api/auth/token/', {
  email: 'teacher@example.com',
  password: 'SecurePassword123!'
});

if (response.data.access_token) {
  // Success - redirect to dashboard
  localStorage.setItem('access_token', response.data.access_token);
  router.push('/dashboard');
} else if (response.data.error === 'Approval pending') {
  // Show pending message
  showMessage('Your registration is pending approval.');
}
```

### Management Dashboard

```typescript
// GET /api/billing/management/registration-requests/?status=pending
const requests = await axios.get(
  '/api/billing/management/registration-requests/?status=pending',
  { headers: { Authorization: `Bearer ${managementToken}` } }
);

// Approve request
// POST /api/billing/management/registration-requests/{id}/approve/
await axios.post(
  `/api/billing/management/registration-requests/${requestId}/approve/`,
  { notes: 'Approved after verification' },
  { headers: { Authorization: `Bearer ${managementToken}` } }
);
```

## Testing

Complete test script available at `/tmp/test_complete_flow.sh`

**Test Coverage:**
1. ✓ Registration with unauthorized email (403)
2. ✓ Registration with authorized email (202)
3. ✓ Login attempt before approval (403)
4. ✓ Management approval (200)
5. ✓ Login after approval (200 with tokens)

## Related Documentation

- [DJANGO_ADMIN_SETUP.md](./DJANGO_ADMIN_SETUP.md) - Setting up Django admin and OAuth
- [CLAUDE.md](../CLAUDE.md) - Complete project documentation including OAuth flow

## API Endpoints Summary

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/auth/register/` | POST | Public | Register new user |
| `/api/auth/token/` | POST | Public | Login and get JWT tokens |
| `/api/billing/management/registration-requests/` | GET | Management | List registration requests |
| `/api/billing/management/registration-requests/{id}/approve/` | POST | Management | Approve request |
| `/api/billing/management/registration-requests/{id}/reject/` | POST | Management | Reject request |
