# Billing App

The Billing app handles all user management, lesson scheduling, and invoicing for the Maple Key Music Academy backend.

## 🏗️ Architecture Overview

This app implements a **unified User model** with role-based permissions supporting three user types:
- **Management** - Full system access, can approve teachers, manage invoices
- **Teachers** - Can teach lessons, manage their own students/lessons
- **Students** - Can request lessons, view their own information

## 📊 Models

### User Model (Custom User)
```python
class User(AbstractUser):
    user_type = models.CharField(choices=[('management', 'Management'), ('teacher', 'Teacher'), ('student', 'Student')])
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    is_approved = models.BooleanField(default=False)
    oauth_provider = models.CharField(max_length=50, blank=True)
    oauth_id = models.CharField(max_length=100, blank=True)
    
    # Teacher-specific fields
    bio = models.TextField(blank=True)
    instruments = models.CharField(max_length=500, blank=True)
    hourly_rate = models.DecimalField(max_digits=6, decimal_places=2, default=65.00)
    
    # Student-specific fields
    assigned_teacher = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    parent_email = models.EmailField(blank=True)
    parent_phone = models.CharField(max_length=15, blank=True)
```

**Key Features:**
- Uses email as username (no separate username field)
- Auto-approves management users
- Supports OAuth integration (Google)
- Role-based field access

### Lesson Model
```python
class Lesson(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lessons_teaching')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lessons_taking')
    rate = models.DecimalField(max_digits=6, decimal_places=2, default=65.00)
    scheduled_date = models.DateTimeField()
    completed_date = models.DateTimeField(null=True, blank=True)
    duration = models.DecimalField(max_digits=4, decimal_places=2, default=1.0)
    status = models.CharField(choices=[('requested', 'Requested'), ('confirmed', 'Confirmed'), ('completed', 'Completed'), ('cancelled', 'Cancelled')])
    teacher_notes = models.TextField(blank=True)
    student_notes = models.TextField(blank=True)
```

**Key Features:**
- Default rate of $80/hour
- Automatic rate setting from teacher's hourly rate
- Status tracking for lesson workflow
- Notes for both teacher and student

### Invoice Model
```python
class Invoice(models.Model):
    invoice_type = models.CharField(choices=[('teacher_payment', 'Teacher Payment'), ('student_billing', 'Student Billing')])
    lessons = models.ManyToManyField(Lesson)
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    student = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    payment_balance = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(choices=[('draft', 'Draft'), ('pending', 'Pending'), ('approved', 'Approved'), ('paid', 'Paid'), ('overdue', 'Overdue')])
    due_date = models.DateTimeField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
```

**Key Features:**
- Two invoice types: teacher payments and student billing
- Automatic payment balance calculation
- Approval workflow with tracking
- Audit trail of who created/approved

## 🔗 API Endpoints

### User Management
- `GET /api/billing/teachers/` - Public teacher directory (approved teachers only)
- `POST /api/billing/teachers/` - Create teacher (management only)
- `GET /api/billing/teachers/all/` - All teachers including pending (management only)
- `POST /api/billing/teachers/{id}/approve/` - Approve pending teacher (management only)
- `GET /api/billing/students/` - Student list (students see themselves, management sees all)

### Lesson Management
- `GET /api/billing/lessons/` - List lessons (teachers see their own, management sees all)
- `POST /api/billing/lessons/` - Create lesson (teachers/management)
- `POST /api/billing/lessons/request/` - Student requests lesson from teacher
- `POST /api/billing/lessons/{id}/confirm/` - Teacher confirms lesson request
- `POST /api/billing/lessons/{id}/complete/` - Teacher marks lesson as completed

### Invoice Management
- `GET /api/billing/invoices/teacher/` - Teacher payment invoices
- `POST /api/billing/invoices/teacher/` - Create teacher payment invoice
- `POST /api/billing/invoices/teacher/submit-lessons/` - **NEW: Teacher submits lesson details and creates invoice**
- `POST /api/billing/invoices/teacher/{id}/approve/` - Management approves teacher invoice

### Detail Views
- `GET/PUT/DELETE /api/billing/teachers/{id}/` - Teacher detail (public GET, auth required for PUT/DELETE)
- `GET/PUT/DELETE /api/billing/students/{id}/` - Student detail (role-based access)
- `GET/PUT/DELETE /api/billing/lessons/{id}/` - Lesson detail (role-based access)
- `GET/PUT/DELETE /api/billing/invoices/{id}/` - Invoice detail (role-based access)

## 🔐 Permission System

### Role-Based Access Control
- **Management**: Full access to all endpoints and data
- **Teachers**: Can only access their own lessons, students, and invoices
- **Students**: Can only access their own data and request lessons

### Approval System
- **Management**: Auto-approved, full access immediately
- **Teachers**: Must be approved by management before full access
- **Students**: Must be approved by management before full access

## 💰 Invoicing Workflows

### Teacher Payment Flow
1. Teacher completes lessons
2. Teacher submits monthly lesson form via `/api/billing/invoices/teacher/submit-lessons/`
3. System creates lessons and invoice automatically
4. Invoice status: `pending` (awaiting management approval)
5. Management approves via `/api/billing/invoices/teacher/{id}/approve/`
6. Invoice status: `approved` → `paid`
7. School processes payment to teacher

### Student Billing Flow (Future)
1. Management creates invoice for upcoming lessons
2. Student pays in advance
3. Lessons get scheduled and can be rescheduled/canceled
4. Teacher completes lessons and submits for payment
5. Management pays teacher from student pre-payments

## 🎯 Key Features

### Smart Student/Lesson Creation
- **Teacher Form Submission**: Automatically creates students and lessons if they don't exist
- **Flexible Student Lookup**: Finds existing students by email or creates new ones
- **Default Rate Handling**: Uses teacher's hourly rate if not specified

### Automatic Calculations
- **Lesson Total Cost**: `rate × duration`
- **Invoice Payment Balance**: Sum of all lesson costs in the invoice
- **Rate Defaults**: $80/hour default, teacher custom rates override

### Audit Trail
- **Created By**: Tracks who created each invoice
- **Approved By**: Tracks who approved each invoice
- **Timestamps**: Creation and approval times recorded

## 🧪 Testing

Run the architecture test suite:
```bash
python test_architecture.py
```

This tests:
- User creation with different roles
- JWT authentication
- Role-based permissions
- Lesson workflow
- Invoice system
- Error handling

## 🔧 Django Admin

The app includes comprehensive Django admin configuration:
- **User Admin**: Role-based fieldsets, search, filtering
- **Lesson Admin**: Status filtering, cost display
- **Invoice Admin**: Type filtering, recipient display

Access at: `http://localhost:8000/admin/`

## 📝 Usage Examples

### Teacher Submits Monthly Lessons
```python
POST /api/billing/invoices/teacher/submit-lessons/
{
    "month": "January 2024",
    "lessons": [
        {
            "student_name": "John Smith",
            "student_email": "john@example.com",
            "scheduled_date": "2024-01-15T14:00:00Z",
            "duration": 1.0,
            "rate": 65.00,
            "teacher_notes": "Worked on scales"
        }
    ],
    "due_date": "2024-02-15T00:00:00Z"
}
```

### Management Approves Invoice
```python
POST /api/billing/invoices/teacher/123/approve/
Authorization: Bearer <management_token>
```

### Student Requests Lesson
```python
POST /api/billing/lessons/request/
{
    "teacher": 5,
    "scheduled_date": "2024-01-20T16:00:00Z",
    "duration": 1.0
}
```

## 🚀 Future Enhancements

- Student billing invoice creation
- Payment processing integration
- Email notifications
- Calendar integration
- Advanced reporting and analytics
- Mobile app support
