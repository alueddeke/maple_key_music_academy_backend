# Maple Key Music Academy Backend

A Django REST API backend for a music school management system with role-based authentication, student management, lesson scheduling, and dual invoicing.

---

## 🚀 New Developer? Start Here!

**This is the backend repository.** For complete setup instructions including all three repositories (backend, frontend, docker), see:

**📖 [DEVELOPER_WORKFLOW.md](../DEVELOPER_WORKFLOW.md)** - Complete guide from first-time setup to production deployment

**Quick Links:**
- [First-Time Setup](../DEVELOPER_WORKFLOW.md#first-time-setup) - Get up and running (includes Django admin setup)
- [Working on a Feature](../DEVELOPER_WORKFLOW.md#working-on-a-new-feature) - Daily development workflow
- [Database Migrations](../DEVELOPER_WORKFLOW.md#handling-database-migrations) - How to handle model changes
- [Deployment Guide](../DEVELOPER_WORKFLOW.md#submitting-to-production) - Deploying to production

**Important:** This backend runs inside Docker. Don't run `pip install` locally - use the Docker workflow!

---

## 🏗️ System Architecture

### Core Components

- **Unified User Model** - Single model supporting Management, Teachers, and Students
- **Role-Based Permissions** - Different access levels for different user types
- **Mixed Authentication** - OAuth (Google) + JWT token authentication
- **Student Management System** - Students with billable contacts for invoicing
- **Lesson Management** - Scheduling, confirmation, and completion workflow
- **Dual Invoicing System** - Teacher payments and student billing

### Apps Structure

```
maple_key_music_academy_backend/
├── billing/           # User management, students, lessons, invoices
├── custom_auth/       # Authentication and authorization
├── maple_key_backend/ # Django project settings
└── requirements.txt   # Python dependencies
```

---

## 🚀 Quick Start (Docker - Recommended)

**Note:** We use Docker for development. See [DEVELOPER_WORKFLOW.md](../DEVELOPER_WORKFLOW.md) for complete setup.

```bash
# Navigate to the docker repository
cd ../maple_key_music_academy_docker

# Start all services (backend + frontend + database)
docker compose up

# The backend will be running at http://localhost:8000
# API endpoints at http://localhost:8000/api/
# Django Admin at http://localhost:8000/admin/
```

**After first startup, you must configure Django admin:**
- Create superuser: `docker compose exec api python manage.py createsuperuser`
- See [Django Admin Setup](#-django-admin-setup) section below for required configuration

## Alternative: Local Development (Without Docker)

Only use this if you cannot use Docker:

```bash
# Clone repository
git clone <repository-url>
cd maple_key_music_academy_backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your settings

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Start development server
python manage.py runserver
```

---

## 📊 Core Models

### User Model (Custom User in billing app)

```python
class User(AbstractUser):
    user_type = models.CharField(choices=[
        ('management', 'Management'),
        ('teacher', 'Teacher'),
        ('student', 'Student')
    ])
    email = models.EmailField(unique=True)  # Used as username
    phone_number = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    province_state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True)
    is_approved = models.BooleanField(default=False)
    oauth_provider = models.CharField(max_length=50, blank=True)
    oauth_id = models.CharField(max_length=100, blank=True)

    # Teacher-specific fields
    bio = models.TextField(blank=True)
    instruments = models.CharField(max_length=500, blank=True)
    hourly_rate = models.DecimalField(max_digits=6, decimal_places=2, default=80.00)
```

**Key Features:**
- Uses email as `USERNAME_FIELD` (no separate username)
- Auto-approves management users
- Supports OAuth integration (Google)
- Role-based field access

### Student Model

```python
class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15, blank=True)
    date_of_birth = models.DateField()
    assigned_teachers = models.ManyToManyField(User, related_name='assigned_students')
    is_active = models.BooleanField(default=True)  # Soft delete
```

**Key Features:**
- Separate from User model (students don't need login accounts)
- Many-to-many relationship with teachers
- Age calculation from date_of_birth
- Soft delete with is_active flag

### BillableContact Model

```python
class BillableContact(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    contact_type = models.CharField(choices=[
        ('parent', 'Parent'),
        ('guardian', 'Guardian'),
        ('self', 'Self'),
        ('other', 'Other')
    ])
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    province_state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    is_primary = models.BooleanField(default=False)
```

**Key Features:**
- One-to-many: Student can have multiple billable contacts
- Exactly one primary contact required per student (enforced on save)
- Full address for invoicing
- When `contact_type='self'`, student is their own billable contact

### Lesson Model

```python
class Lesson(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    billable_contact = models.ForeignKey(BillableContact, on_delete=models.CASCADE)
    lesson_type = models.CharField(choices=[
        ('in_person', 'In Person'),
        ('online', 'Online')
    ])
    rate = models.DecimalField(max_digits=6, decimal_places=2)
    scheduled_date = models.DateTimeField()
    duration = models.DecimalField(max_digits=4, decimal_places=2, default=1.0)
    status = models.CharField(choices=[
        ('requested', 'Requested'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ])
    teacher_notes = models.TextField(blank=True)
```

**Key Features:**
- Automatic rate setting based on lesson_type:
  - `online` → $45/hour
  - `in_person` → teacher's hourly_rate
- Status workflow: requested → confirmed → completed
- FK to Student (not User) for proper student management

### Invoice Model

```python
class Invoice(models.Model):
    invoice_type = models.CharField(choices=[
        ('teacher_payment', 'Teacher Payment'),
        ('student_billing', 'Student Billing')
    ])
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True)
    billable_contact = models.ForeignKey(BillableContact, on_delete=models.CASCADE, null=True)
    lessons = models.ManyToManyField(Lesson)
    payment_balance = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(choices=[
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue')
    ])
    due_date = models.DateTimeField()
    rejection_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
```

**Key Features:**
- Two invoice types: teacher_payment (school pays teacher) and student_billing (student pays school)
- Automatic payment balance calculation from lessons
- Approval workflow with tracking
- Rejection with reason
- PDF generation for both types

---

## 🔐 Authentication System

### JWT Token Authentication

```bash
# Login
POST /api/auth/token/
{
    "email": "teacher@example.com",
    "password": "password123"
}

# Response
{
    "access_token": "...",
    "refresh_token": "...",
    "user": {
        "email": "teacher@example.com",
        "user_id": 123,
        "user_type": "teacher",
        "is_approved": true
    }
}
```

**Token Configuration:**
- Access token: 1 hour
- Refresh token: 1 day
- Blacklist on logout
- Bearer authentication header

### Google OAuth

```bash
# Initiate OAuth
GET /api/auth/google/
# → Redirects to Google
# → Google redirects to /api/auth/google/callback/
# → Returns JWT tokens
```

**OAuth Setup Requirements:**
1. Google Cloud Console: Create OAuth 2.0 credentials
2. Django Admin: Configure Social App (see Django Admin Setup section)
3. Environment Variables: Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`

### User Approval System

**Database-Driven Approval** (no hardcoded email whitelist):

**Three Approval Paths:**

1. **Pre-Approval (Invitation):**
   - Management adds email to `ApprovedEmail` table
   - User receives 48-hour invitation link
   - User sets up account (auto-approved)

2. **Open Registration:**
   - User submits registration request
   - Creates `UserRegistrationRequest` (status: pending)
   - Management reviews and approves/rejects
   - Approved users receive invitation link

3. **OAuth Registration:**
   - User attempts OAuth login
   - If not pre-approved, creates pending `UserRegistrationRequest`
   - Management approves
   - User can login

**Models:**
- `User.is_approved` - Boolean flag (auto-true for management)
- `ApprovedEmail` - Pre-approved emails awaiting registration
- `UserRegistrationRequest` - Pending registration requests
- `InvitationToken` - Secure 48-hour tokens for account setup

**Password Reset:**
- Available to existing users only
- Standard Django password reset flow

### Role-Based Permissions

**Permission Decorators:**

```python
@role_required('teacher', 'management')
def endpoint(request):
    # Only teachers and management can access
    pass

@management_required
def management_endpoint(request):
    # Only management can access
    pass

@owns_resource_or_management('teacher')
def resource_endpoint(request):
    # Teachers can access their own, management can access all
    pass
```

**Permission Logic:**
1. Verifies JWT token is valid
2. Checks user has required role
3. Ensures account is approved (management auto-approved)
4. Validates resource ownership (for non-management users)

---

## 📚 API Endpoints

### Authentication

```
POST   /api/auth/token/                  # Get JWT tokens (email/password)
POST   /api/auth/token/refresh/          # Refresh access token
POST   /api/auth/logout/                 # Blacklist refresh token
GET    /api/auth/google/                 # Initiate Google OAuth
GET    /api/auth/google/callback/        # OAuth callback handler
GET    /api/auth/user/                   # Get current user profile
POST   /api/auth/register/               # Register new user (email/password)
```

### User Approval (Management Only)

```
GET    /api/billing/management/registration-requests/               # List requests
POST   /api/billing/management/registration-requests/{id}/approve/  # Approve request
POST   /api/billing/management/registration-requests/{id}/reject/   # Reject request
GET    /api/billing/management/approved-emails/                     # List pre-approved emails
POST   /api/billing/management/approved-emails/                     # Add pre-approved email
DELETE /api/billing/management/approved-emails/{id}/                # Remove pre-approved email
GET    /api/billing/management/users/                               # List all users
```

### Student Management (Management Only)

```
GET    /api/billing/management/students/                            # List all students
POST   /api/billing/management/students/                            # Create new student
GET    /api/billing/management/students/{id}/                       # Get student detail
PATCH  /api/billing/management/students/{id}/                       # Update student
DELETE /api/billing/management/students/{id}/                       # Delete student (soft delete)
POST   /api/billing/management/students/{id}/assign-teacher/        # Assign teacher to student
DELETE /api/billing/management/students/{id}/teachers/{teacher_id}/ # Remove teacher assignment
```

### Billable Contact Management (Management Only)

```
GET    /api/billing/management/students/{id}/billable-contacts/     # List student's contacts
POST   /api/billing/management/students/{id}/billable-contacts/     # Add billable contact
GET    /api/billing/management/billable-contacts/{id}/              # Get contact detail
PATCH  /api/billing/management/billable-contacts/{id}/              # Update contact
DELETE /api/billing/management/billable-contacts/{id}/              # Delete contact
```

### Teacher Endpoints

```
GET    /api/billing/teachers/              # Public teacher directory (approved only)
GET    /api/billing/teachers/all/          # All teachers including pending (management only)
GET    /api/billing/teachers/me/students/  # Get teacher's assigned students
GET    /api/billing/teachers/{id}/         # Teacher detail (public)
PUT    /api/billing/teachers/{id}/         # Update teacher (auth required)
DELETE /api/billing/teachers/{id}/         # Delete teacher (management only)
POST   /api/billing/teachers/{id}/approve/ # Approve teacher (management only)
```

### Lesson Management

```
GET    /api/billing/lessons/                # List lessons (role-based access)
POST   /api/billing/lessons/                # Create lesson (teachers/management)
GET    /api/billing/lessons/{id}/           # Lesson detail
PUT    /api/billing/lessons/{id}/           # Update lesson
DELETE /api/billing/lessons/{id}/           # Delete lesson
POST   /api/billing/lessons/request/        # Student requests lesson
POST   /api/billing/lessons/{id}/confirm/   # Teacher confirms lesson
POST   /api/billing/lessons/{id}/complete/  # Teacher marks lesson completed
```

### Invoice Management

#### Teacher Invoices
```
GET    /api/billing/invoices/teacher/                    # List teacher's invoices
POST   /api/billing/invoices/teacher/submit-lessons/     # Submit lessons and create invoice
GET    /api/billing/invoices/teacher/{id}/               # Teacher invoice detail
POST   /api/billing/invoices/teacher/{id}/approve/       # Approve invoice (management)
POST   /api/billing/invoices/teacher/{id}/reject/        # Reject invoice (management)
GET    /api/billing/invoices/teacher/{id}/pdf/           # Download teacher invoice PDF
```

**Submit Lessons Endpoint:**
```json
POST /api/billing/invoices/teacher/submit-lessons/
{
  "lessons": [
    {
      "student_id": 1,                       # Required: Student FK
      "billable_contact_id": 1,              # Required: BillableContact FK
      "lesson_type": "in_person",            # Required: "in_person" | "online"
      "scheduled_date": "2024-01-15T14:00:00Z",
      "duration": 1.0,
      "rate": 80.00,                         # Auto-set based on lesson_type
      "teacher_notes": "Great progress"
    }
  ]
}

Response (201 Created):
{
  "message": "Lessons submitted and invoice created successfully",
  "invoice": { ... },
  "lessons_created": 1,
  "student_invoices_created": 1
}
```

#### Student Invoices
```
GET    /api/billing/invoices/student/               # List student invoices
GET    /api/billing/invoices/student/{id}/          # Student invoice detail
GET    /api/billing/invoices/student/{id}/pdf/      # Download student invoice PDF
```

#### Management Invoice Overview
```
GET    /api/billing/invoices/management/            # All invoices (teacher + student)
GET    /api/billing/invoices/{id}/                  # Invoice detail (any type)
```

---

## 💰 Invoicing Workflows

### Teacher Payment Flow

1. Teacher completes lessons throughout the month
2. Teacher submits monthly form with lesson details via `/api/billing/invoices/teacher/submit-lessons/`
   - Includes: student_id, billable_contact_id, lesson_type, duration, scheduled_date
3. System creates lessons and teacher_payment invoice automatically
   - Rates auto-set: online=$45, in_person=teacher.hourly_rate
4. Invoice status: `pending` (awaiting management approval)
5. Management approves via `/api/billing/invoices/teacher/{id}/approve/`
   - Or rejects via `/api/billing/invoices/teacher/{id}/reject/` with reason
6. Invoice status: `approved` → school processes payment to teacher
7. Invoice status: `paid`

### Student Billing Flow

1. Teacher submits lessons (same as above)
2. System automatically creates student_billing invoice per (student, billable_contact) pair
3. Student invoice includes all lessons for that student
4. Invoice shows billable contact's address in "BILL TO" section
5. PDF generated with lesson details and payment instructions

---

## 🧪 Django Admin Setup

After running migrations for the first time, you **must** configure Django admin:

### 1. Create Superuser

```bash
docker compose exec api python manage.py createsuperuser
```

### 2. Configure Django Site (Required for OAuth)

**Why:** The application uses `SITE_ID = 2` in settings.py.

**Steps:**
1. Login to Django admin: `http://localhost:8000/admin/`
2. Navigate to **Sites** (under SITES)
3. Click **Add Site**
4. Create site with:
   - **Domain:** `localhost:8000` (dev) or `api.maplekeymusic.com` (prod)
   - **Display name:** `Maple Key Music Academy`
   - Save

**Important:** Site ID must be 2 to match settings.

### 3. Configure Google OAuth Social Application

**Prerequisites:**
- Google OAuth credentials (Client ID and Secret) from Google Cloud Console
- Credentials also set in environment variables

**Steps:**
1. In Django admin, navigate to **Social applications** (under SOCIAL ACCOUNTS)
2. Click **Add social application**
3. Fill in:
   - **Provider:** Google
   - **Name:** Google OAuth
   - **Client id:** Your Google OAuth Client ID
   - **Secret key:** Your Google OAuth Client Secret
   - **Sites:** Select the site you created (ID=2)
   - Save

### 4. Verify Configuration

Test OAuth flow:
- Visit frontend: `http://localhost:5173/login`
- Click "Continue with Google"
- Should redirect to Google, then back to your application

**Troubleshooting:**
- "Google OAuth app not configured" → Complete step 3
- "Site matching query does not exist" → Complete step 2
- "Redirect URI mismatch" → Add redirect URI in Google Cloud Console:
  - Dev: `http://localhost:8000/api/auth/google/callback/`
  - Prod: `https://api.maplekeymusic.com/api/auth/google/callback/`

---

## 🔧 Environment Variables

### Required Variables

**Security:**
- `SECRET_KEY` - Django secret key (required, no default)
- `DEBUG` - Debug mode (`True` for dev, `False` for prod)
- `ALLOWED_HOSTS` - Comma-separated: `localhost,127.0.0.1,api.maplekeymusic.com`

**Frontend Integration:**
- `FRONTEND_URL` - OAuth redirect destination
  - Dev: `http://localhost:5173`
  - Prod: `https://maplekeymusic.com`
- `CORS_ALLOWED_ORIGINS` - Frontend origins
  - Dev: `*` or `http://localhost:5173`
  - Prod: `https://maplekeymusic.com`

**Google OAuth:**
- `GOOGLE_CLIENT_ID` - Google OAuth client ID
- `GOOGLE_CLIENT_SECRET` - Google OAuth secret

### Database Variables

**Option 1: PostgreSQL URL (production)**
```bash
DATABASE_URL=postgresql://user:password@host:port/dbname
```

**Option 2: Individual vars (local dev)**
```bash
POSTGRES_DB=maple_key_dev
POSTGRES_USER=maple_key_user
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=db  # Docker service name
POSTGRES_PORT=5432
```

### Email Variables (Optional for local dev)

```bash
EMAIL_HOST_USER=your-gmail@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
```

### Production-Only Variables

```bash
CERTBOT_EMAIL=admin@yourdomain.com
DOCKER_USERNAME=your-dockerhub-username
DOCKER_PASSWORD=your-dockerhub-token
VPC_HOST=your-backend-droplet-ip
VPC_USERNAME=your-ssh-username
VPC_SSH_KEY=your-ssh-private-key
VPC_PORT=22
```

---

## 🧪 Testing

### Run Architecture Tests

```bash
python test_architecture.py
```

**Tests include:**
- ✅ User creation with different roles
- ✅ JWT authentication
- ✅ Role-based permissions
- ✅ Lesson workflow
- ✅ Invoice system
- ✅ Error handling

### Manual API Testing

Use Postman, curl, or the frontend to test API endpoints.

**Example: Create Student and Submit Invoice**

```bash
# 1. Login as management
curl -X POST http://localhost:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin123"}'

# 2. Create student
curl -X POST http://localhost:8000/api/billing/management/students/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name":"John",
    "last_name":"Smith",
    "email":"john@example.com",
    "date_of_birth":"2010-05-15"
  }'

# 3. Add billable contact
curl -X POST http://localhost:8000/api/billing/management/students/1/billable-contacts/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "contact_type":"parent",
    "first_name":"Jane",
    "last_name":"Smith",
    "email":"jane@example.com",
    "phone":"416-555-1234",
    "address_line1":"123 Main St",
    "city":"Toronto",
    "province_state":"Ontario",
    "postal_code":"M1M 1M1",
    "country":"Canada",
    "is_primary":true
  }'

# 4. Assign teacher to student
curl -X POST http://localhost:8000/api/billing/management/students/1/assign-teacher/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"teacher_id":2}'

# 5. Teacher creates invoice
curl -X POST http://localhost:8000/api/billing/invoices/teacher/submit-lessons/ \
  -H "Authorization: Bearer TEACHER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "lessons":[
      {
        "student_id":1,
        "billable_contact_id":1,
        "lesson_type":"in_person",
        "scheduled_date":"2024-01-15T14:00:00Z",
        "duration":1.0,
        "teacher_notes":"Great progress"
      }
    ]
  }'
```

---

## 👥 User Types & Roles

### Management

- **Auto-approved** - No approval required
- **Full system access** - Can view and manage all data
- **Django admin access** - Can access admin interface
- **Invoice approval** - Can approve/reject teacher payment invoices
- **User management** - Can approve teachers/students, manage registration requests

### Teachers

- **Approval required** - Must be approved by management
- **Lesson management** - Can create, confirm, and complete lessons
- **Student access** - Can view/manage assigned students only
- **Invoice creation** - Can submit monthly lesson invoices
- **Profile management** - Can edit own profile

### Students

- **Approval required** - Must be approved by management (for User accounts)
- **Lesson requests** - Can request lessons from teachers
- **Own data access** - Can view their own lessons and invoices
- **Note:** Most students don't need User accounts - they're managed via Student model

---

## 🔒 Security Features

### Token Security
- Short-lived access tokens (1 hour)
- Refresh token rotation available
- Token blacklisting on logout
- HTTPS required in production

### Permission Security
- Role-based access control (RBAC)
- Resource ownership validation
- Approval status checking
- Audit trail for all actions

### OAuth Security
- State parameter validation
- Secure token exchange
- User data validation
- Account linking for existing users

### Database Security
- PostgreSQL with proper credentials
- Environment variable configuration
- No hardcoded secrets
- Password hashing (PBKDF2)

---

## 📖 Documentation

**Essential Guides:**
- [DEVELOPER_WORKFLOW.md](../DEVELOPER_WORKFLOW.md) - Complete developer workflow from setup to deployment
- [CLAUDE.md](../CLAUDE.md) - Complete project overview and architecture

---

## 🚀 Future Enhancements

- [ ] Payment processing integration (Stripe, Square)
- [ ] Email notifications (lesson confirmations, invoice reminders)
- [ ] Calendar integration (Google Calendar, iCal)
- [ ] Video call integration (Zoom, Google Meet)
- [ ] Mobile app support (React Native)
- [ ] Advanced analytics and reporting
- [ ] Multi-language support
- [ ] Automated testing suite expansion

---

## 📄 License

This project is licensed under the MIT License.
