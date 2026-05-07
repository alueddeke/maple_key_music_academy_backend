from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models, transaction
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from simple_history.models import HistoricalRecords

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


class School(models.Model): 
    # 1. Basic Info
    name = models.CharField(max_length=150)
    # A subdomain is the 'maplekey' in 'maplekey.yourapp.com'
    subdomain = models.SlugField(max_length=150, unique=True, help_text="Used for the URL")
    # For images, we use ImageField (requires 'Pillow' library)
    logo = models.ImageField(upload_to='school_logos/', null=True, blank=True)
    primary_color = models.CharField(max_length=7, default="#000000", help_text="Hex color code")

    # 2. Canadian Tax (Use Decimal for currency/tax, never Integer)
    # max_digits=5, decimal_places=2 allows up to 999.99
    hst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=13.00)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5.00)
    pst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    tax_number = models.CharField(max_length=50, blank=True)

    # 3. Billing & Policy
    billing_cycle_day = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Day of the month (1-31)"
    )
    payment_terms_days = models.PositiveIntegerField(default=7)
    cancellation_notice_hours = models.PositiveIntegerField(default=24)

    # 4. Contact Info
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True)
    street_address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    province = models.CharField(max_length=2, default='ON')
    postal_code = models.CharField(max_length=7)

    # 5. Status & Timestamps
    is_active = models.BooleanField(default=True)
    # auto_now_add sets time ONLY when created. auto_now updates every time you save.
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Audit logging
    history = HistoricalRecords()

# labels this model using "name"
    def __str__(self):
        return self.name

class SchoolSettings(models.Model):
    # link to school model name
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name='settings')
    # rates
    online_teacher_rate = models.DecimalField(max_digits=6, decimal_places=2, default=45.00)
    online_student_rate = models.DecimalField(max_digits=6, decimal_places=2, default=60.00)
    inperson_student_rate = models.DecimalField(max_digits=6, decimal_places=2, default=100.00)
    # Deprecated field
    invoice_recipient_email = models.EmailField(blank=True, null=True, help_text="DEPRECATED")

    # Payment terms for Helcim CSV export
    payment_terms = models.CharField(max_length=50, default="Due in 15 days", help_text="Default payment terms for student invoices")
    management_notification_email = models.EmailField(blank=True, help_text="Email for management notifications (future use)")

    # tracking
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='school_settings_updates')

    # Audit logging
    history = HistoricalRecords()

    @classmethod
    def get_settings_for_school(cls, school):
        """Get existing settings or create them with defaults"""
        settings, created = cls.objects.get_or_create(school=school)
        return settings
    def __str__(self):
        return f"Settings for {self.school.name}"



class User(AbstractUser):
    USER_TYPES = [
        ('management', 'Management'),
        ('teacher', 'Teacher'), 
        ('student', 'Student'),
    ]

    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name='users',
        help_text="School this user belongs to"
    )

    # Core fields
    user_type = models.CharField(max_length=20, choices=USER_TYPES)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)

    # Remove the username field since we're using email
    username = None
    
    # Status fields
    is_approved = models.BooleanField(default=False, help_text="Management approval for teachers/students")
    is_active = models.BooleanField(default=True, help_text="Soft delete flag - False means user is deleted")
    oauth_provider = models.CharField(max_length=50, blank=True)  # 'google', etc.
    oauth_id = models.CharField(max_length=100, blank=True)
    
    # Teacher-specific fields
    bio = models.TextField(blank=True)
    instruments = models.CharField(max_length=500, blank=True, help_text="Comma-separated list of instruments")
    hourly_rate = models.DecimalField(max_digits=6, decimal_places=2, default=50.00)
    
    # Student-specific fields
    assigned_teachers = models.ManyToManyField(
        'self',
        symmetrical=False,
        related_name='assigned_students',
        limit_choices_to={'user_type': 'teacher'},
        blank=True
    )
    # Override to use email as username
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'user_type']

    # Use our custom manager
    objects = UserManager()

    # Audit logging
    history = HistoricalRecords()

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


class BillableContact(models.Model):
    """Billable contact for student invoices - supports multiple"""
    CONTACT_TYPES = [
        ('parent', 'Parent'),
        ('guardian', 'Guardian'),
        ('self', 'Self'),
        ('other', 'Other'),
    ]
    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name='billable_contacts',
        help_text="School this billable contact belongs to"
    )

    # Relationships
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='billable_contacts',
        limit_choices_to={'user_type': 'student'}
    )

    # Contact type
    contact_type = models.CharField(max_length=20, choices=CONTACT_TYPES, default='parent')

    # Contact information
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=15)

    # Full address for billing (Canadian format)
    street_address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    province = models.CharField(max_length=2, help_text="Province code (e.g., ON, BC, QC)")
    postal_code = models.CharField(max_length=10, help_text="Postal code (e.g., M5H 2N2)")

    # Primary contact flag (used for invoicing)
    is_primary = models.BooleanField(
        default=False,
        help_text="Primary contact receives invoices"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Audit logging
    history = HistoricalRecords()

    class Meta:
        ordering = ['-is_primary', '-created_at']
        verbose_name = 'Billable Contact'
        verbose_name_plural = 'Billable Contacts'

    def save(self, *args, **kwargs):
        """Ensure exactly one primary contact per student"""
        if self.is_primary:
            # Unset any other primary contacts for this student
            BillableContact.objects.filter(
                student=self.student,
                is_primary=True
            ).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        primary_label = " (Primary)" if self.is_primary else ""
        return f"{self.get_full_name()} - {self.get_contact_type_display()}{primary_label}"

class Lesson(models.Model):
    LESSON_STATUS = [
        ('requested', 'Requested'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    LESSON_TYPES = [
        ('in_person', 'In Person'),
        ('online', 'Online'),
    ]
    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name='lessons',
        help_text="School this lesson belongs to"
    )

    # Updated foreign keys to use User
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lessons_teaching',
                               limit_choices_to={'user_type': 'teacher'})
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lessons_taking',
                               limit_choices_to={'user_type': 'student'})

    # Lesson details
    lesson_type = models.CharField(max_length=20, choices=LESSON_TYPES, default='in_person')
    is_trial = models.BooleanField(default=False, help_text="Trial lesson - student not charged, teacher still paid")
    teacher_rate = models.DecimalField(max_digits=6, decimal_places=2, default=50.00, help_text="Rate paid to teacher for this lesson")
    student_rate = models.DecimalField(max_digits=6, decimal_places=2, default=100.00, help_text="Rate billed to student for this lesson")
    scheduled_date = models.DateTimeField(null=True, blank=True)
    completed_date = models.DateTimeField(null=True, blank=True)
    duration = models.DecimalField(max_digits=6, decimal_places=2, default=1.0)
    status = models.CharField(max_length=20, choices=LESSON_STATUS, default='requested')

    # Cancellation tracking
    cancelled_by_type = models.CharField(
        max_length=20,
        choices=[
            ('teacher', 'Teacher Cancelled'),
            ('student', 'Student Cancelled'),
        ],
        blank=True,
        null=True,
        help_text="Who cancelled the lesson (affects billing)"
    )
    cancellation_reason = models.TextField(
        blank=True,
        help_text="Optional reason for cancellation"
    )

    # Link to recurring schedule (if this lesson came from one)
    recurring_schedule = models.ForeignKey(
        'RecurringLessonsSchedule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_lessons',
        help_text="The recurring schedule that generated this lesson"
    )

    # Notes
    teacher_notes = models.TextField(blank=True)
    student_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Audit logging
    history = HistoricalRecords()
    
    def total_cost(self):
        """Calculate total cost using teacher_rate (for teacher invoices)"""
        from decimal import Decimal
        # Use teacher_rate for dual-rate system
        rate = Decimal(str(self.teacher_rate)) if not isinstance(self.teacher_rate, Decimal) else self.teacher_rate
        duration = Decimal(str(self.duration)) if not isinstance(self.duration, Decimal) else self.duration
        # CRITICAL: Return Decimal for money precision, not float
        return rate * duration

    def student_cost(self):
        """Calculate total cost using student_rate (for student invoices)"""
        from decimal import Decimal
        # Use student_rate for dual-rate system
        rate = Decimal(str(self.student_rate)) if not isinstance(self.student_rate, Decimal) else self.student_rate
        duration = Decimal(str(self.duration)) if not isinstance(self.duration, Decimal) else self.duration
        # CRITICAL: Return Decimal for money precision, not float
        return rate * duration
    

    @staticmethod
    def student_has_completed_lesson(student):
        """
        Check if student has completed any lessons.
        Used to determine if lesson should be default or trial.

        Args:
            student: User instance with user_type='student'

        Returns:
            bool: True if student has at least one completed lesson, False otherwise
        """
        return Lesson.objects.filter(
            student=student,
            status='completed'
        ).exists()
    
    def save(self, *args, **kwargs):
        from decimal import Decimal

        # Auto detect if trial lesson/first time students
        # only run if lesson is being created for a student for the first time
        if not self.pk and not hasattr(self, '_skip_trial_auto_detection'):
            if not self.student_has_completed_lesson(self.student):
                # If is_trial is still the default False and student has no completed lessons,
                # only auto-detect if the field wasn't explicitly set in object creation
                # We check if _is_trial_explicitly_set was set by views.py
                if not hasattr(self, '_is_trial_explicitly_set'):
                    self.is_trial = True


        # Auto-set teacher_rate and student_rate if not already set (rate locking at creation)
        # Only set rates for new lessons (pk is None) and if both rates are still at model defaults
        if not self.pk and (self.teacher_rate == Decimal('50.00') and self.student_rate == Decimal('100.00')):
            # find school settings
            settings = None
            # try to get rates from teacher's school
            if self.teacher and getattr(self.teacher, 'school', None):
                settings = SchoolSettings.get_settings_for_school(self.teacher.school)

            if not settings:
                try:
                    # using legacy rate settings
                    settings = GlobalRateSettings.get_settings()
                except:
                    settings = None

            # Determine rates based on lesson type
            if self.lesson_type == 'online':
                # Use settings rates if found, legacy otherwise
                self.teacher_rate = settings.online_teacher_rate if settings else Decimal('45.00')
                base_student_rate = settings.online_student_rate if settings else Decimal('60.00')
            else:
                # In-person lesson rates, individual to teacher per school
                self.teacher_rate = self.teacher.hourly_rate if self.teacher else Decimal('50.00')
                base_student_rate = settings.inperson_student_rate if settings else Decimal('100.00')

            # if lesson is trial, student pays $0
            self.student_rate = Decimal('0.00') if self.is_trial else base_student_rate

        # If lesson is marked as trial after rates were set, update student_rate to $0
        elif self.is_trial and self.student_rate != Decimal('0.00'):
            self.student_rate = Decimal('0.00')

        super().save(*args, **kwargs)
    
    def __str__(self):
        trial_indicator = " [TRIAL]" if self.is_trial else ""
        return f"{self.student.get_full_name()} - {self.teacher.get_full_name()} - {self.scheduled_date}{trial_indicator}"
    
class RecurringLessonsSchedule(models.Model):
    """Weekly recurring lesson schedule for teacher-student pairs"""
    DAYS_OF_WEEK = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    # Relationships
    teacher = models.ForeignKey(User,on_delete=models.CASCADE, related_name='teaching_schedules', limit_choices_to={'user_type':'teacher'})
    student = models.ForeignKey(User,on_delete=models.CASCADE, related_name='student_schedules', limit_choices_to={'user_type':'student'})
    school = models.ForeignKey('School',on_delete=models.PROTECT, related_name='recurring_lesson_schedules')

    # Schedule Details
    day_of_week = models.IntegerField(choices=DAYS_OF_WEEK) 
    start_time = models.TimeField(help_text="Lesson start time (eg. 15:00)")
    duration = models.DecimalField(max_digits=4, decimal_places=2, default=1.0, help_text="Duration in hours")

    # Lesson Type
    lesson_type = models.CharField(max_length=20, choices=Lesson.LESSON_TYPES, default='in_person')

    #Rates (locked at schedule creation like the lesson)
    teacher_rate = models.DecimalField(max_digits=6, decimal_places=2)
    student_rate = models.DecimalField(max_digits=6, decimal_places=2)

    # Active Status
    is_active = models.BooleanField(default=True, help_text="Set to False to pause/end this recurring schedule")
    start_date = models.DateField(help_text="When this recurring schedule begins")
    end_date = models.DateField(null=True, blank=True, help_text="Optional end date to track")

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_schedules' )

    # audit logging
    history = HistoricalRecords()

    class Meta:
        ordering = ['day_of_week', 'start_time']
        verbose_name = 'Recurring Lesson Schedule'
        verbose_name_plural = 'Recurring Lesson Schedules'
        # prevent duplicate schedules
        unique_together = ['teacher', 'student', 'day_of_week', 'start_time']

    def save(self, *args, **kwargs):
        """auto-set rates and school if not provided"""
        from decimal import Decimal

        #autoset school from teacher
        if not self.school_id and self.teacher:
            self.school = self.teacher.school
        # autoset rates if not provided (rate locking)
        if self.teacher_rate is None or self.student_rate is None:
            settings = SchoolSettings.get_settings_for_school(self.school)

            if self.lesson_type == 'online':
                self.teacher_rate = settings.online_teacher_rate
                self.student_rate = settings.online_student_rate
            else:
                self.teacher_rate = self.teacher.hourly_rate if self.teacher else Decimal('50.00')
                self.student_rate = settings.inperson_student_rate
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.teacher.get_full_name()} → {self.student.get_full_name()} | {self.get_day_of_week_display()} {self.start_time}"
    
    def generate_lessons_for_month(self, year, month):
        """
        Calculate which dates this schedule would occur in given month.
        Return list of date objects(does NOT create the lesson records).
        Example: "every monday", returns all mondays in that month
        """
        import calendar 
        from datetime import date, timedelta

        if not self.is_active:
            return []
        #get all days in month
        num_days = calendar.monthrange(year, month)[1]
        month_start = date(year, month, 1)
        month_end = date(year, month, num_days)

        # Jump directly to first occurrence of day_of_week in this month
        # weekday() returns 0=Monday...6=Sunday, same as DAYS_OF_WEEK
        days_until_target = (self.day_of_week - month_start.weekday()) % 7
        first_occurrence = month_start + timedelta(days=days_until_target)

        lesson_dates = []
        current_date = first_occurrence

        while current_date <= month_end:
            if current_date >= self.start_date:
                if self.end_date is None or current_date <= self.end_date:
                    lesson_dates.append(current_date)
            current_date += timedelta(days=7)

        return lesson_dates

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
        ('rejected', 'Rejected'),
        ('overdue', 'Overdue')
    ]

    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name='invoices',
        help_text="School this invoice belongs to"
    )

    # Core fields
    invoice_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    invoice_type = models.CharField(max_length=20, choices=INVOICE_TYPES)
    lessons = models.ManyToManyField(Lesson)

    # User relationships (either teacher OR student, not both)
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True,
                               related_name='teacher_invoices', limit_choices_to={'user_type': 'teacher'})
    student = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True,
                               related_name='student_invoices', limit_choices_to={'user_type': 'student'})

    # Invoice details
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
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

    # Rejection tracking
    rejected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='invoices_rejected',
                                   limit_choices_to={'user_type': 'management'})
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, help_text="Reason for rejection (visible to teacher)")

    # Management editing tracking
    notes = models.TextField(blank=True, help_text="Management notes about this invoice")
    last_edited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='invoices_edited',
                                      limit_choices_to={'user_type': 'management'})
    last_edited_at = models.DateTimeField(null=True, blank=True)

    # Audit logging
    history = HistoricalRecords()

    def calculate_payment_balance(self):
        from decimal import Decimal
        total = Decimal('0.00')

        for lesson in self.lessons.all():
            # Use appropriate rate based on invoice type
            if self.invoice_type == 'teacher_payment':
                # Teachers are paid their teacher_rate
                rate = lesson.teacher_rate
            else:  # student_billing
                # Students are billed the student_rate
                rate = lesson.student_rate

            # Calculate cost for this lesson
            duration = Decimal(str(lesson.duration))
            total += rate * duration

        return total

    def can_be_edited(self):
        """Check if invoice can be edited by management"""
        return self.status in ['draft', 'pending']

    def generate_invoice_number(self):
        """Generate unique invoice number: INV-YYYY-MM-NNNN"""
        from datetime import datetime
        today = datetime.now()
        year = today.strftime('%Y')
        month = today.strftime('%m')

        prefix = f"INV-{year}-{month}"

        with transaction.atomic():
            last_invoice = Invoice.objects.filter(
                invoice_number__startswith=prefix
            ).select_for_update().order_by('-invoice_number').first()

            if last_invoice and last_invoice.invoice_number:
                try:
                    last_seq = int(last_invoice.invoice_number.split('-')[-1])
                    new_seq = last_seq + 1
                except (ValueError, IndexError):
                    new_seq = 1
            else:
                new_seq = 1

        return f"{prefix}-{new_seq:04d}"

    def save(self, *args, **kwargs):
        # Ensure only one of teacher or student is set
        if self.invoice_type == 'teacher_payment' and self.student:
            self.student = None
        elif self.invoice_type == 'student_billing' and self.teacher:
            self.teacher = None

        # Calculate payment balance and total_amount
        if self.pk:  # Only if instance already exists (has lessons)
            calculated_total = self.calculate_payment_balance()
            self.payment_balance = calculated_total
            self.total_amount = calculated_total

        if not self.invoice_number:
            # Outer atomic ensures the select_for_update() lock inside
            # generate_invoice_number() is held until super().save() inserts
            # the row — inner atomic() becomes a savepoint, lock held by outer.
            with transaction.atomic():
                self.invoice_number = self.generate_invoice_number()
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
    
    def __str__(self):
        if self.invoice_type == 'teacher_payment':
            return f"Payment to {self.teacher.get_full_name()} - {self.payment_balance}"
        else:
            return f"Bill for {self.student.get_full_name()} - {self.payment_balance}"


class MonthlyInvoiceBatch(models.Model):
    """
    Temporary container for invoices to live before management approval.
    Represents teacher monthly invoice submission.
    """

    BATCH_STATUS = [
        ('draft', 'Draft'),  # Teacher hasn't submitted yet
        ('submitted', 'Submitted'),  # Waiting for management review
        ('approved', 'Approved'),  # Management approved, Lesson records created
        ('rejected', 'Rejected'),  # Management rejected
    ]

    PAYMENT_METHODS = [
        ('e-transfer', 'E-Transfer'),
        ('cheque', 'Cheque'),
        ('direct_deposit', 'Direct Deposit'),
    ]

    # ID
    batch_number = models.CharField(max_length=50, unique=True, blank=True)

    # relationships
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoice_batches', limit_choices_to={'user_type': 'teacher'})
    school = models.ForeignKey('School', on_delete=models.PROTECT, related_name='invoice_batches' )

    # time period
    month = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    year = models.IntegerField(validators=[MinValueValidator(2020)])
    
    # Status
    status = models.CharField(max_length=20, choices=BATCH_STATUS, default='draft')

    # Submission tracking
    submitted_at = models.DateTimeField(null=True, blank=True)

    # approval/rejection
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_batches', limit_choices_to={'user_type':'management'})
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # linked invoice
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_batch',
        help_text='The teacher payment invoice created from this batch'
    )

    # payment tracking
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS,
        blank=True,
        null=True,
        help_text="Payment method used for this batch"
    )
    payment_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date when payment was processed"
    )

    # tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Audit Logging
    history = HistoricalRecords()

    class Meta:
        ordering = ['-year', 'month', 'created_at']
        verbose_name = 'Monthly Invoice Batch'
        verbose_name_plural = 'Monthly Invoice Batches'
        # one batch per teacher per month
        unique_together = ['teacher', 'month', 'year']

    def generate_batch_number(self):
        """Generate unique batch number: BATCH-YYYY-MM-TEACHER_ID-NNNN"""
        if not self.batch_number:
            
            prefix = f"BATCH-{self.year}-{self.month:02d}-T{self.teacher.id}"
            # find the "last one in db"
            # find all batches starting with that prefix
            # sort them by number, "-" means descending, newest first
            # give me only the top one, most recent
            last_batch = MonthlyInvoiceBatch.objects.filter(
                batch_number__startswith=prefix
            ).order_by('-batch_number').first()
            if last_batch:
                try:
                    last_seq = int(last_batch.batch_number.split('-')[-1])
                    new_seq = last_seq + 1
                except (ValueError, IndexError):
                    new_seq = 1
            else:
                new_seq = 1
            self.batch_number = f"{prefix}-{new_seq:04d}"

    def save(self, *args, **kwargs):
        # auto gen batch number
        self.generate_batch_number()

        # autoset school from teacher
        if not self.school_id and self.teacher:
            self.school = self.teacher.school
        # set submitted_at timestampe when status changes to submitted
        if self.status == 'submitted' and not self.submitted_at:
            self.submitted_at = timezone.now()
        
        # set reviewed_at when status changes to approved/rejected
        if self.status in ['approved', 'rejected'] and not self.reviewed_at:
            self.reviewed_at = timezone.now()
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.batch_number} - {self.teacher.get_full_name()} - {self.year}-{self.month:02d} ({self.get_status_display()})"
    
    def get_scheduled_lessons_data(self):
        """
        Generate list of expected lessons for this month based on teacher's RecurringLessonsSchedule records.
        Returns list of dicts - no actual lesson objects
        """

        schedules = self.teacher.teaching_schedules.filter(
            is_active=True,
            school=self.school,
            student__is_active=True  # Only include schedules for active students
        )

        lessons_data = []

        for schedule in schedules:
            # get dates this sched occurs in this month
            dates = schedule.generate_lessons_for_month(self.year, self.month)

            for lesson_date in dates:
                lessons_data.append({                    
                    'recurring_schedule': schedule,
                    'scheduled_date': lesson_date,
                    'start_time': schedule.start_time,
                    'student': schedule.student,
                    'teacher': schedule.teacher,
                    'duration': schedule.duration,
                    'lesson_type': schedule.lesson_type,
                    'teacher_rate': schedule.teacher_rate,
                    'student_rate': schedule.student_rate,
                    # Default status (teacher can change via UI)
                    'status': 'completed',
                    'cancelled_by_type': None,
                    'cancellation_reason': '',})
        return lessons_data

class BatchLessonItem(models.Model):
    """
    Individual lesson within a MonthlyInvoiceBatch. 
    Stores lesson data before management approval.
    Gets deleted after Lesson records are created on management approval
    """
    # parent batch
    batch = models.ForeignKey(MonthlyInvoiceBatch, on_delete=models.CASCADE, related_name='lesson_items')

    # lesson details (duplicates the Lesson model fields)
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+', limit_choices_to={'user_type':'student'})
    scheduled_date = models.DateField()
    start_time = models.TimeField()
    duration = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    lesson_type = models.CharField(max_length=20, choices=Lesson.LESSON_TYPES)

    # Rates (locked from recurring schedule or entered manually)
    teacher_rate = models.DecimalField(max_digits=6, decimal_places=2)
    student_rate = models.DecimalField(max_digits=6, decimal_places=2)

    # status (teacher marks this)
    status = models.CharField(max_length=20, choices=Lesson.LESSON_STATUS, default='completed')
    cancelled_by_type = models.CharField(max_length=20, choices=[('teacher', 'Teacher'), ('student', 'Student')], blank=True, null=True)
    cancellation_reason = models.TextField(blank=True)

    # Notes
    teacher_notes = models.TextField(blank=True)

    # link to recurring sched (if from schedule)
    recurring_schedule = models.ForeignKey(
        RecurringLessonsSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    # One-off lesson flag
    is_one_off = models.BooleanField(
        default=False,
        help_text="True if teacher added this manually (not from recurring schedule)"
    )

    # Created lesson (after approval)
    created_lesson = models.ForeignKey(
        Lesson,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text="Actual Lesson record created when batch was approved"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['scheduled_date', 'start_time']
        verbose_name = 'Batch Lesson Item'
        verbose_name_plural = 'Batch Lesson Items'

    def __str__(self):
        return f"{self.batch.batch_number} | {self.scheduled_date} | {self.student.get_full_name()}"

    def calculate_teacher_payment(self):
        """Calculate what teacher gets paid for this lesson"""
        from decimal import Decimal

        # If cancelled by anyone (teacher or student), teacher doesn't get paid
        # Future: may add cancellation policy where teacher gets paid for student cancellations
        if self.status == 'cancelled':
            return Decimal('0.00')

        # Otherwise, pay teacher_rate × duration
        return self.teacher_rate * self.duration

    def calculate_student_charge(self):
        """Calculate what student is billed for this lesson"""
        from decimal import Decimal

        # If cancelled (by anyone), student not charged
        if self.status == 'cancelled':
            return Decimal('0.00')

        # If completed, charge student_rate × duration
        return self.student_rate * self.duration


class StudentInvoice(models.Model):
    """
    Student invoice generated when management approves a batch.
    One invoice per student per batch, containing all completed lessons for that student.
    Used to generate Helcim CSV for student billing.
    """
    # Parent batch
    batch = models.ForeignKey(
        MonthlyInvoiceBatch,
        on_delete=models.CASCADE,
        related_name='student_invoices',
        help_text="The batch this invoice was generated from"
    )

    # Student
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='helcim_invoices',
        limit_choices_to={'user_type': 'student'},
        help_text="Student this invoice is for"
    )

    # School
    school = models.ForeignKey(
        'School',
        on_delete=models.PROTECT,
        related_name='student_invoices'
    )

    # Invoice number: INV-YYYY-MM-S{student_id}-NNNN
    invoice_number = models.CharField(max_length=50, unique=True)

    # Total amount to charge student (sum of all completed lesson charges)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    # Lesson items included in this invoice (completed lessons only)
    lesson_items = models.ManyToManyField(
        BatchLessonItem,
        related_name='student_invoice',
        help_text="Completed lessons included in this invoice"
    )

    # Cached billable contact data (from student's primary contact at generation time)
    # This ensures invoice data doesn't change if student updates their contact info later
    billing_contact_name = models.CharField(max_length=200)
    billing_email = models.EmailField()
    billing_phone = models.CharField(max_length=20)
    billing_street_address = models.CharField(max_length=200)
    billing_city = models.CharField(max_length=100)
    billing_province = models.CharField(max_length=2)  # 2-letter province code
    billing_postal_code = models.CharField(max_length=10)

    # Timestamps
    generated_at = models.DateTimeField(auto_now_add=True)

    # Audit logging
    history = HistoricalRecords()

    class Meta:
        ordering = ['-generated_at']
        verbose_name = 'Student Invoice'
        verbose_name_plural = 'Student Invoices'
        # One invoice per student per batch
        unique_together = ['batch', 'student']

    def __str__(self):
        return f"{self.invoice_number} - {self.student.get_full_name()} - ${self.amount}"

    def generate_invoice_number(self):
        """Generate unique invoice number: INV-YYYY-MM-S{student_id}-NNNN"""
        if not self.invoice_number:
            prefix = f"INV-{self.batch.year}-{self.batch.month:02d}-S{self.student.id}"

            with transaction.atomic():
                last_invoice = StudentInvoice.objects.filter(
                    invoice_number__startswith=prefix
                ).select_for_update().order_by('-invoice_number').first()

                if last_invoice:
                    try:
                        last_seq = int(last_invoice.invoice_number.split('-')[-1])
                        new_seq = last_seq + 1
                    except (ValueError, IndexError):
                        new_seq = 1
                else:
                    new_seq = 1

                self.invoice_number = f"{prefix}-{new_seq:04d}"

    def calculate_amount(self):
        """Calculate total amount from all associated lesson items"""
        from decimal import Decimal
        total = sum(
            item.calculate_student_charge()
            for item in self.lesson_items.all()
        ) or Decimal('0.00')
        return total

    def save(self, *args, **kwargs):
        if not self.school_id and self.student:
            self.school = self.student.school

        if not self.invoice_number:
            # Outer atomic ensures the select_for_update() lock inside
            # generate_invoice_number() is held until super().save() inserts
            # the row — inner atomic() becomes a savepoint, lock held by outer.
            with transaction.atomic():
                self.generate_invoice_number()
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class ApprovedEmail(models.Model):
    """Pre-approved email addresses that can register without management review"""
    email = models.EmailField(unique=True)
    user_type = models.CharField(max_length=20, choices=User.USER_TYPES)
    approved_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='emails_approved')
    approved_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="Optional notes about this pre-approval")

    # Audit logging
    history = HistoricalRecords()

    class Meta:
        ordering = ['-approved_at']

    def __str__(self):
        return f"{self.email} ({self.get_user_type_display()})"


class UserRegistrationRequest(models.Model):
    """User registration requests pending management approval"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    # User info
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    user_type = models.CharField(max_length=20, choices=User.USER_TYPES)

    # OAuth info (if applicable)
    oauth_provider = models.CharField(max_length=50, blank=True)  # 'google', etc.
    oauth_id = models.CharField(max_length=100, blank=True)

    # Approval workflow
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='registration_requests_reviewed',
                                   limit_choices_to={'user_type': 'management'})
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Management notes about this request")

    # Audit logging
    history = HistoricalRecords()

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"{self.email} - {self.get_status_display()} ({self.get_user_type_display()})"


class InvitationToken(models.Model):
    """Secure tokens for inviting pre-approved users to set up their accounts"""
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True)
    user_type = models.CharField(max_length=20, choices=User.USER_TYPES)
    approved_email = models.ForeignKey(ApprovedEmail, on_delete=models.CASCADE, related_name='invitation_tokens')

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    is_used = models.BooleanField(default=False)

    # Audit logging
    history = HistoricalRecords()

    class Meta:
        ordering = ['-created_at']

    def is_valid(self):
        """Check if token is valid (not expired and not used)"""
        from django.utils import timezone
        return not self.is_used and timezone.now() < self.expires_at

    def mark_as_used(self):
        """Mark token as used"""
        from django.utils import timezone
        self.is_used = True
        self.used_at = timezone.now()
        self.save()

    def __str__(self):
        return f"Invitation for {self.email} - {'Used' if self.is_used else 'Valid' if self.is_valid() else 'Expired'}"


class SystemSettings(models.Model):
    """System-wide settings configurable from the management UI"""
    # Singleton pattern - only one instance should exist
    invoice_recipient_email = models.EmailField(
        help_text='Email address where invoice PDFs are sent'
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='settings_updates')

    # Audit logging
    history = HistoricalRecords()

    class Meta:
        verbose_name = 'System Settings'
        verbose_name_plural = 'System Settings'

    def save(self, *args, **kwargs):
        # Ensure only one instance exists (singleton pattern)
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance"""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

    def __str__(self):
        return 'System Settings'


class GlobalRateSettings(models.Model):
    """Global rate settings for online and in-person lessons"""
    # Singleton pattern - only one instance should exist

    # Online lesson rates
    online_teacher_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=45.00,
        help_text='Rate paid to teachers for online lessons ($/hour)'
    )
    online_student_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=60.00,
        help_text='Rate billed to students for online lessons ($/hour)'
    )

    # In-person lesson rates
    inperson_student_rate = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=100.00,
        help_text='Rate billed to students for in-person lessons ($/hour). Teachers paid their hourly_rate.'
    )

    # Tracking
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rate_settings_updates'
    )

    # Audit logging
    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Global Rate Settings'
        verbose_name_plural = 'Global Rate Settings'

    def save(self, *args, **kwargs):
        # Ensure only one instance exists (singleton pattern)
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance"""
        settings, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                'online_teacher_rate': 45.00,
                'online_student_rate': 60.00,
                'inperson_student_rate': 100.00,
            }
        )
        return settings

    def __str__(self):
        return 'Global Rate Settings'


class InvoiceRecipientEmail(models.Model):
    """Email addresses that receive invoice PDFs when teachers submit"""
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='invoice_recipient_emails',
        help_text="School this invoice recipient belongs to"
    )
    email = models.EmailField(unique=True, help_text='Recipient email address for invoice PDFs')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_recipient_emails'
    )

    # Audit logging
    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Invoice Recipient Email'
        verbose_name_plural = 'Invoice Recipient Emails'
        ordering = ['created_at']

    def __str__(self):
        return self.email