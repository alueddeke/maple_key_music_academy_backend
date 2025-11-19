# Maple Key Music Academy Backend

A Django REST API backend for a music school management system with role-based authentication, lesson scheduling, and invoicing.

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
- **Dual Invoicing System** - Teacher payments and student billing
- **Lesson Management** - Scheduling, confirmation, and completion workflow

### Apps Structure

```
maple_key_music_academy_backend/
├── billing/           # User management, lessons, invoices
├── custom_auth/       # Authentication and authorization
├── maple_key_backend/ # Django project settings
└── requirements.txt   # Python dependencies
```

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
- See [docs/DJANGO_ADMIN_SETUP.md](docs/DJANGO_ADMIN_SETUP.md) for required steps
- This includes setting up Site ID=2 and Google OAuth configuration

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

## 👥 User Types & Roles

### Management

- **Full system access** - Can view and manage all data
- **Auto-approved** - No approval required
- **Admin privileges** - Django admin access
- **Invoice approval** - Can approve teacher payment invoices

### Teachers

- **Lesson management** - Can create, confirm, and complete lessons
- **Student management** - Can manage their own students
- **Invoice creation** - Can submit monthly lesson invoices
- **Approval required** - Must be approved by management

### Students

- **Lesson requests** - Can request lessons from teachers
- **Own data access** - Can view their own lessons and invoices
- **Approval required** - Must be approved by management

## 🔐 Authentication System

### JWT Token Authentication

```bash
# Login
POST /api/auth/token/
{
    "email": "teacher@example.com",
    "password": "password123"
}
```

### Google OAuth

```bash
# Initiate OAuth
GET /api/auth/google/
```

## 📚 Key API Endpoints

### Authentication

- `POST /api/auth/token/` - Get JWT tokens
- `POST /api/auth/token/refresh/` - Refresh access token
- `GET /api/auth/google/` - Initiate Google OAuth
- `GET /api/auth/user/` - Get current user profile

### Lesson Management

- `GET /api/billing/lessons/` - List lessons
- `POST /api/billing/lessons/request/` - Student requests lesson
- `POST /api/billing/lessons/{id}/confirm/` - Teacher confirms lesson

### Invoice Management

- `POST /api/billing/invoices/teacher/submit-lessons/` - **Submit lesson details and create invoice**
- `POST /api/billing/invoices/teacher/{id}/approve/` - Approve invoice

## 💰 Invoicing Workflows

### Teacher Payment Flow

1. Teacher completes lessons throughout the month
2. Teacher submits monthly form with lesson details
3. System creates lessons and invoice automatically
4. Invoice status: pending (awaiting management approval)
5. Management approves invoice
6. School processes payment to teacher

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

## 🔧 Django Admin

Access the admin interface at: `http://localhost:8000/admin/`

## 📖 Documentation

**Essential Guides:**
- [DEVELOPER_WORKFLOW.md](../DEVELOPER_WORKFLOW.md) - Complete developer workflow from setup to deployment
- [DJANGO_ADMIN_SETUP.md](docs/DJANGO_ADMIN_SETUP.md) - Required Django admin configuration
- [EMAIL_PASSWORD_REGISTRATION.md](docs/EMAIL_PASSWORD_REGISTRATION.md) - User registration flow

**Project Documentation:**
- [CLAUDE.md](../CLAUDE.md) - Complete project overview and architecture
- [DEVELOPER_WORKFLOW.md](../DEVELOPER_WORKFLOW.md) - Development workflow and deployment guide

**App-Specific:**
- [Billing App README](billing/README.md) - User management, lessons, invoices
- [Custom Auth App README](custom_auth/README.md) - Authentication and authorization

## 🚀 Future Enhancements

- Student billing invoices (pre-payment system)
- Payment processing integration
- Email notifications
- Calendar integration
- Video call integration
- Mobile app support
- Advanced analytics

## 📄 License

This project is licensed under the MIT License.

change to trigger deploy
