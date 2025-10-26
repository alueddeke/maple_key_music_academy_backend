from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

class UserManager(BaseUserManager):
    
    def create_user(self, email, password=None, **extra_fields):
        """Create and return a regular user with an email and password"""
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return a superuser with an email and password"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('user_type', 'management')
        extra_fields.setdefault('is_approved', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    USER_TYPES = [
        ('management', 'Management'),
        ('teacher', 'Teacher'), 
        ('student', 'Student'),
    ]
    
    # Core fields
    user_type = models.CharField(max_length=20, choices=USER_TYPES)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    
    # Remove the username field since we're using email
    username = None
    
    # Status fields
    is_approved = models.BooleanField(default=False, help_text="Management approval for teachers/students")
    oauth_provider = models.CharField(max_length=50, blank=True)  # 'google', etc.
    oauth_id = models.CharField(max_length=100, blank=True)
    
    # Teacher-specific fields
    bio = models.TextField(blank=True)
    instruments = models.CharField(max_length=500, blank=True, help_text="Comma-separated list of instruments")
    hourly_rate = models.DecimalField(max_digits=6, decimal_places=2, default=80.00)
    
    # Student-specific fields (for future)
    assigned_teacher = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, 
                                       limit_choices_to={'user_type': 'teacher'})
    parent_email = models.EmailField(blank=True)
    parent_phone = models.CharField(max_length=15, blank=True)
    
    # Override to use email as username
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'user_type']
    
    # Use our custom manager
    objects = UserManager()
    
    def save(self, *args, **kwargs):
        # Auto-approve management users
        if self.user_type == 'management':
            self.is_approved = True
            self.is_staff = True
            self.is_superuser = True
        
        super().save(*args, **kwargs)
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.get_user_type_display()})"


class Lesson(models.Model):
    LESSON_STATUS = [
        ('requested', 'Requested'),
        ('confirmed', 'Confirmed'), 
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Updated foreign keys to use User
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lessons_teaching',
                               limit_choices_to={'user_type': 'teacher'})
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lessons_taking',
                               limit_choices_to={'user_type': 'student'})
    
    # Lesson details
    rate = models.DecimalField(max_digits=6, decimal_places=2, default=80.00)
    scheduled_date = models.DateTimeField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    duration = models.DecimalField(max_digits=6, decimal_places=2, default=1.0)  # Increased from 4 to 6 to allow values up to 9999.99
    status = models.CharField(max_length=20, choices=LESSON_STATUS, default='requested')
    
    # Notes
    teacher_notes = models.TextField(blank=True)
    student_notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def total_cost(self):
        from decimal import Decimal
        return float(self.rate * self.duration)
    
    def save(self, *args, **kwargs):
        # Set rate from teacher's hourly rate if not provided and teacher has a custom rate
        if self.rate == 80.00 and self.teacher and self.teacher.hourly_rate != 80.00:
            self.rate = self.teacher.hourly_rate
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.student.get_full_name()} - {self.teacher.get_full_name()} - {self.scheduled_date}"

class Invoice(models.Model):
    INVOICE_TYPES = [
        ('teacher_payment', 'Teacher Payment'),  # School pays teacher
        ('student_billing', 'Student Billing'),  # Student pays school  
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'), 
        ('approved', 'Approved'),
        ('paid', 'Paid'), 
        ('overdue', 'Overdue')
    ]
    
    # Core fields
    invoice_type = models.CharField(max_length=20, choices=INVOICE_TYPES)
    lessons = models.ManyToManyField(Lesson)
    
    # User relationships (either teacher OR student, not both)
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True,
                               related_name='teacher_invoices', limit_choices_to={'user_type': 'teacher'})
    student = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True,
                               related_name='student_invoices', limit_choices_to={'user_type': 'student'})
    
    # Invoice details
    payment_balance = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    due_date = models.DateTimeField(null=True, blank=True)  # Made optional to allow migration
    
    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                  related_name='invoices_created')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='invoices_approved', 
                                   limit_choices_to={'user_type': 'management'})
    approved_at = models.DateTimeField(null=True, blank=True)
    
    def calculate_payment_balance(self):
        total = sum(lesson.total_cost() for lesson in self.lessons.all())
        return total
    
    def save(self, *args, **kwargs):
        # Ensure only one of teacher or student is set
        if self.invoice_type == 'teacher_payment' and self.student:
            self.student = None
        elif self.invoice_type == 'student_billing' and self.teacher:
            self.teacher = None
            
        # Calculate payment balance
        if self.pk:  # Only if instance already exists (has lessons)
            self.payment_balance = self.calculate_payment_balance()
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        if self.invoice_type == 'teacher_payment':
            return f"Payment to {self.teacher.get_full_name()} - {self.payment_balance}"
        else:
            return f"Bill for {self.student.get_full_name()} - {self.payment_balance}"