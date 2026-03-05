from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum, Q
from .models import (
    Lesson, Invoice, ApprovedEmail, UserRegistrationRequest, SystemSettings,
    InvoiceRecipientEmail, GlobalRateSettings, BillableContact,
    School, SchoolSettings, RecurringLessonsSchedule, MonthlyInvoiceBatch, BatchLessonItem
)

User = get_user_model()
class BillableContactSerializer(serializers.ModelSerializer):
    """Serializer for billable contact information"""
    contact_type_display = serializers.CharField(source='get_contact_type_display', read_only=True)
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True)

    class Meta:
        model = BillableContact
        fields = [
            'id', 'student', 'school', 'school_name', 'contact_type', 'contact_type_display',
            'first_name', 'last_name', 'full_name',
            'email', 'phone',
            'street_address', 'city', 'province', 'postal_code',
            'is_primary', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'contact_type_display', 'full_name', 'school_name']

    def validate(self, data):
        """Ensure at least one primary contact per student"""
        student = data.get('student')
        is_primary = data.get('is_primary', False)

        # If unsetting primary, ensure another primary exists
        if not is_primary and self.instance and self.instance.is_primary:
            other_primaries = BillableContact.objects.filter(
                student=student,
                is_primary=True
            ).exclude(pk=self.instance.pk).exists()

            if not other_primaries:
                raise serializers.ValidationError({
                    'is_primary': 'At least one primary contact is required per student'
                })

        return data
class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    user_type_display = serializers.CharField(source='get_user_type_display', read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True)
    billable_contacts = BillableContactSerializer(many=True, read_only=True)
    assigned_teachers_data = serializers.SerializerMethodField()
    assigned_students_data = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'user_type', 'user_type_display',
            'school', 'school_name',
            'phone_number', 'address', 'is_approved', 'is_active',
            'bio', 'instruments', 'hourly_rate',
            'assigned_teachers', 'assigned_teachers_data',
            'assigned_students_data',
            'billable_contacts',
            'parent_email', 'parent_phone',  # DEPRECATED fields
            'date_joined', 'last_login', 'password'
        ]
        read_only_fields = ['id', 'date_joined', 'last_login', 'user_type_display', 'school_name']
        extra_kwargs = {'password': {'write_only': True}}

    def get_assigned_teachers_data(self, obj):
        """Return full teacher info for students"""
        if obj.user_type == 'student':
            return [
                {
                    'id': teacher.id,
                    'name': teacher.get_full_name(),
                    'email': teacher.email,
                    'instruments': teacher.instruments
                }
                for teacher in obj.assigned_teachers.filter(is_active=True)
            ]
        return []

    def get_assigned_students_data(self, obj):
        """Return full student info for teachers"""
        if obj.user_type == 'teacher':
            return [
                {
                    'id': student.id,
                    'name': student.get_full_name(),
                    'email': student.email,
                    'phone': student.phone_number
                }
                for student in obj.assigned_students.filter(is_active=True)
            ]
        return []

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = User.objects.create_user(**validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user


class LessonSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True)
    total_cost = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    student_cost = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_first_lesson = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = '__all__'

    def get_is_first_lesson(self, obj):
        """Check if this is the student's first lesson (for UI display)"""
        if obj.pk:  # Existing lesson
            return False
        # For new lessons, check if student has completed lessons
        return not Lesson.student_has_completed_lesson(obj.student)

    def validate(self, data):
        """Custom validation for trial lessons"""
        # Prevent changing is_trial after lesson is completed
        if self.instance and self.instance.status == 'completed':
            if 'is_trial' in data and data['is_trial'] != self.instance.is_trial:
                raise serializers.ValidationError({
                    'is_trial': 'Cannot change trial status after lesson is completed'
                })

        return data

class InvoiceSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)

    class Meta:
        model = Invoice
        fields = '__all__'

class RecurringScheduleSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    day_of_week_display = serializers.CharField(source='get_day_of_week_display', read_only=True)

    class Meta:
        model = RecurringLessonsSchedule
        fields = [
            'id', 'teacher', 'teacher_name', 'student', 'student_name',
            'day_of_week', 'day_of_week_display', 'start_time', 'duration',
            'lesson_type', 'teacher_rate', 'student_rate',
            'is_active', 'start_date', 'end_date',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['teacher_rate', 'student_rate', 'created_at', 'updated_at']

class BatchLessonItemSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    teacher_payment = serializers.DecimalField(
        source='calculate_teacher_payment',
        max_digits=10,
        decimal_places=2,
        read_only=True
    )
    student_charge = serializers.DecimalField(
        source='calculate_student_charge',
        max_digits=10,
        decimal_places=2,
        read_only=True
    )
    class Meta:
        model = BatchLessonItem
        fields = [
            'id', 'student', 'student_name',
            'scheduled_date', 'start_time', 'duration',
            'lesson_type', 'teacher_rate', 'student_rate',
            'status', 'cancelled_by_type', 'cancellation_reason',
            'teacher_notes', 'is_one_off',
            'teacher_payment', 'student_charge',
            'created_at'
        ]
        read_only_fields = ['teacher_payment', 'student_charge', 'created_at']

class MonthlyInvoiceBatchSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)
    lesson_items = BatchLessonItemSerializer(many=True, read_only=True)
    total_teacher_payment = serializers.SerializerMethodField()
    total_student_charges = serializers.SerializerMethodField()
    lesson_count = serializers.SerializerMethodField()

    class Meta:
        model = MonthlyInvoiceBatch
        fields = [
            'id', 'batch_number', 'teacher', 'teacher_name',
            'month', 'year', 'status',
            'submitted_at', 'reviewed_by', 'reviewed_at',
            'rejection_reason', 'invoice',
            'lesson_items', 'total_teacher_payment', 'total_student_charges',
            'lesson_count', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'batch_number', 'submitted_at', 'reviewed_by', 'reviewed_at',
            'invoice', 'created_at', 'updated_at'
        ]

    def get_total_teacher_payment(self, obj):
        from decimal import Decimal
        return sum(
            item.calculate_teacher_payment()
            for item in obj.lesson_items.all()
        ) or Decimal('0.00')

    def get_total_student_charges(self, obj):
        from decimal import Decimal
        return sum(
            item.calculate_student_charge()
            for item in obj.lesson_items.all()
        ) or Decimal('0.00')

    def get_lesson_count(self, obj):
        return obj.lesson_items.count()

# Management serializers for new approval system
class ApprovedEmailSerializer(serializers.ModelSerializer):
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)
    user_type_display = serializers.CharField(source='get_user_type_display', read_only=True)

    class Meta:
        model = ApprovedEmail
        fields = ['id', 'email', 'user_type', 'user_type_display', 'approved_by', 'approved_by_name', 'approved_at', 'notes']
        read_only_fields = ['approved_at']


class UserRegistrationRequestSerializer(serializers.ModelSerializer):
    reviewed_by_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True)
    user_type_display = serializers.CharField(source='get_user_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = UserRegistrationRequest
        fields = [
            'id', 'email', 'first_name', 'last_name', 'user_type', 'user_type_display',
            'oauth_provider', 'oauth_id', 'status', 'status_display',
            'requested_at', 'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'notes'
        ]
        read_only_fields = ['requested_at', 'reviewed_at']


class DetailedUserSerializer(serializers.ModelSerializer):
    """Detailed user serializer for management with all fields"""
    user_type_display = serializers.CharField(source='get_user_type_display', read_only=True)
    billable_contacts = BillableContactSerializer(many=True, read_only=True)
    assigned_teachers_data = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'user_type', 'user_type_display',
            'phone_number', 'address', 'is_approved', 'is_active', 'oauth_provider', 'oauth_id',
            'bio', 'instruments', 'hourly_rate',
            'assigned_teachers', 'assigned_teachers_data',
            'billable_contacts',
            'parent_email', 'parent_phone', 'date_joined', 'last_login'
        ]
        read_only_fields = ['date_joined', 'last_login']

    def get_assigned_teachers_data(self, obj):
        """Return full teacher info for students"""
        if obj.user_type == 'student':
            return [
                {
                    'id': teacher.id,
                    'name': teacher.get_full_name(),
                    'email': teacher.email,
                    'instruments': teacher.instruments
                }
                for teacher in obj.assigned_teachers.filter(is_active=True)
            ]
        return []


class DetailedInvoiceSerializer(serializers.ModelSerializer):
    """Detailed invoice serializer for management with nested lessons"""
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)
    rejected_by_name = serializers.CharField(source='rejected_by.get_full_name', read_only=True)
    last_edited_by_name = serializers.CharField(source='last_edited_by.get_full_name', read_only=True)
    lessons = LessonSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    invoice_type_display = serializers.CharField(source='get_invoice_type_display', read_only=True)
    can_be_edited = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = '__all__'

    def get_can_be_edited(self, obj):
        return obj.can_be_edited()


class SystemSettingsSerializer(serializers.ModelSerializer):
    """Serializer for system settings"""
    updated_by_name = serializers.CharField(source='updated_by.get_full_name', read_only=True)

    class Meta:
        model = SystemSettings
        fields = ['id', 'invoice_recipient_email', 'updated_at', 'updated_by', 'updated_by_name']
        read_only_fields = ['id', 'updated_at', 'updated_by', 'updated_by_name']


class InvoiceRecipientEmailSerializer(serializers.ModelSerializer):
    """Serializer for invoice recipient emails"""
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True)

    class Meta:
        model = InvoiceRecipientEmail
        fields = ['id', 'school', 'school_name', 'email', 'created_at', 'created_by', 'created_by_name']
        read_only_fields = ['id', 'created_at', 'created_by', 'created_by_name', 'school_name']




class GlobalRateSettingsSerializer(serializers.ModelSerializer):
    """Serializer for global rate settings (singleton) - DEPRECATED, use SchoolSettingsSerializer"""
    updated_by_name = serializers.CharField(source='updated_by.get_full_name', read_only=True)

    class Meta:
        model = GlobalRateSettings
        fields = [
            'id', 'online_teacher_rate', 'online_student_rate', 'inperson_student_rate',
            'updated_at', 'updated_by', 'updated_by_name'
        ]
        read_only_fields = ['id', 'updated_at', 'updated_by', 'updated_by_name']


class SchoolSerializer(serializers.ModelSerializer):
    """Basic school serializer for school information"""

    class Meta:
        model = School
        fields = [
            'id', 'name', 'subdomain', 'logo', 'primary_color',
            'hst_rate', 'gst_rate', 'pst_rate', 'tax_number',
            'billing_cycle_day', 'payment_terms_days', 'cancellation_notice_hours',
            'email', 'phone_number',
            'street_address', 'city', 'province', 'postal_code',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class SchoolDetailSerializer(serializers.ModelSerializer):
    """Detailed school serializer with computed stats"""
    user_count = serializers.SerializerMethodField()
    teacher_count = serializers.SerializerMethodField()
    student_count = serializers.SerializerMethodField()
    lesson_count = serializers.SerializerMethodField()
    invoice_total = serializers.SerializerMethodField()

    class Meta:
        model = School
        fields = [
            'id', 'name', 'subdomain', 'logo', 'primary_color',
            'hst_rate', 'gst_rate', 'pst_rate', 'tax_number',
            'billing_cycle_day', 'payment_terms_days', 'cancellation_notice_hours',
            'email', 'phone_number',
            'street_address', 'city', 'province', 'postal_code',
            'is_active', 'created_at', 'updated_at',
            # Stats
            'user_count', 'teacher_count', 'student_count', 'lesson_count', 'invoice_total'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_user_count(self, obj):
        """Total users in this school"""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.filter(school=obj).count()

    def get_teacher_count(self, obj):
        """Total teachers in this school"""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.filter(school=obj, user_type='teacher').count()

    def get_student_count(self, obj):
        """Total students in this school"""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.filter(school=obj, user_type='student').count()

    def get_lesson_count(self, obj):
        """Total lessons for this school"""
        return Lesson.objects.filter(school=obj).count()

    def get_invoice_total(self, obj):
        """Total invoiced amount for teacher payments"""
        from decimal import Decimal
        total = Invoice.objects.filter(
            school=obj,
            invoice_type='teacher_payment',
            status__in=['approved', 'paid']
        ).aggregate(total=Sum('payment_balance'))['total']
        return total or Decimal('0.00')


class SchoolSettingsSerializer(serializers.ModelSerializer):
    """Serializer for school-specific settings"""
    updated_by_name = serializers.CharField(source='updated_by.get_full_name', read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True)

    class Meta:
        model = SchoolSettings
        fields = [
            'id', 'school', 'school_name',
            'online_teacher_rate', 'online_student_rate', 'inperson_student_rate',
            'invoice_recipient_email',  # DEPRECATED field
            'updated_at', 'updated_by', 'updated_by_name'
        ]
        read_only_fields = ['id', 'school', 'school_name', 'updated_at', 'updated_by', 'updated_by_name']


class TeacherListSerializer(serializers.ModelSerializer):
    """Teacher list with computed stats for management dashboard"""
    # Computed stats fields
    total_students = serializers.SerializerMethodField()
    total_lessons = serializers.SerializerMethodField()
    total_invoices = serializers.SerializerMethodField()
    pending_invoices = serializers.SerializerMethodField()
    total_earnings = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'hourly_rate',
            'instruments', 'is_approved',
            'total_students', 'total_lessons', 'total_invoices',
            'pending_invoices', 'total_earnings'
        ]

    def get_total_students(self, obj):
        """Count distinct students this teacher has taught"""
        return Lesson.objects.filter(teacher=obj, status='completed').values('student').distinct().count()

    def get_total_lessons(self, obj):
        """Count completed lessons for this teacher"""
        return Lesson.objects.filter(teacher=obj, status='completed').count()

    def get_total_invoices(self, obj):
        """Count all invoices for this teacher"""
        return Invoice.objects.filter(teacher=obj, invoice_type='teacher_payment').count()

    def get_pending_invoices(self, obj):
        """Count pending invoices for this teacher"""
        return Invoice.objects.filter(
            teacher=obj,
            invoice_type='teacher_payment',
            status='pending'
        ).count()

    def get_total_earnings(self, obj):
        """Calculate total paid earnings (approved + paid invoices)"""
        from decimal import Decimal
        total = Invoice.objects.filter(
            teacher=obj,
            invoice_type='teacher_payment',
            status__in=['approved', 'paid']
        ).aggregate(total=Sum('payment_balance'))['total']
        return total or Decimal('0.00')


class TeacherDetailSerializer(serializers.ModelSerializer):
    """Detailed teacher info with expanded stats"""
    # Basic stats
    total_students = serializers.SerializerMethodField()
    total_lessons = serializers.SerializerMethodField()
    total_invoices = serializers.SerializerMethodField()
    pending_invoices = serializers.SerializerMethodField()
    total_earnings = serializers.SerializerMethodField()

    # Recent activity
    recent_lessons = serializers.SerializerMethodField()
    recent_invoices = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'phone_number', 'address',
            'hourly_rate', 'bio', 'instruments', 'is_approved',
            'total_students', 'total_lessons', 'total_invoices',
            'pending_invoices', 'total_earnings',
            'recent_lessons', 'recent_invoices',
            'date_joined', 'last_login'
        ]

    def get_total_students(self, obj):
        return Lesson.objects.filter(teacher=obj, status='completed').values('student').distinct().count()

    def get_total_lessons(self, obj):
        return Lesson.objects.filter(teacher=obj, status='completed').count()

    def get_total_invoices(self, obj):
        return Invoice.objects.filter(teacher=obj, invoice_type='teacher_payment').count()

    def get_pending_invoices(self, obj):
        return Invoice.objects.filter(
            teacher=obj,
            invoice_type='teacher_payment',
            status='pending'
        ).count()

    def get_total_earnings(self, obj):
        from decimal import Decimal
        total = Invoice.objects.filter(
            teacher=obj,
            invoice_type='teacher_payment',
            status__in=['approved', 'paid']
        ).aggregate(total=Sum('payment_balance'))['total']
        return total or Decimal('0.00')

    def get_recent_lessons(self, obj):
        """Get 5 most recent completed lessons"""
        lessons = Lesson.objects.filter(
            teacher=obj,
            status='completed'
        ).order_by('-completed_date')[:5]
        return LessonSerializer(lessons, many=True).data

    def get_recent_invoices(self, obj):
        """Get 5 most recent invoices"""
        invoices = Invoice.objects.filter(
            teacher=obj,
            invoice_type='teacher_payment'
        ).order_by('-created_at')[:5]
        return InvoiceSerializer(invoices, many=True).data
class BillingContactInputSerializer(serializers.Serializer):
    """Serializer for billing contact input (without student field) - Canadian format"""
    contact_type = serializers.ChoiceField(choices=['parent', 'guardian', 'self', 'other'], default='parent')
    first_name = serializers.CharField(max_length=150, min_length=1, error_messages={
        'required': 'First name is required',
        'min_length': 'First name cannot be empty'
    })
    last_name = serializers.CharField(max_length=150, min_length=1, error_messages={
        'required': 'Last name is required',
        'min_length': 'Last name cannot be empty'
    })
    email = serializers.EmailField(error_messages={
        'required': 'Email is required',
        'invalid': 'Please enter a valid email address'
    })
    phone = serializers.CharField(max_length=15, min_length=1, error_messages={
        'required': 'Phone number is required',
        'min_length': 'Phone number cannot be empty'
    })
    street_address = serializers.CharField(max_length=255, min_length=1, error_messages={
        'required': 'Street address is required',
        'min_length': 'Street address cannot be empty'
    })
    city = serializers.CharField(max_length=100, min_length=1, error_messages={
        'required': 'City is required',
        'min_length': 'City cannot be empty'
    })
    province = serializers.CharField(max_length=2, min_length=2, error_messages={
        'required': 'Province is required',
        'min_length': 'Province must be 2 characters (e.g., ON, BC, QC)',
        'max_length': 'Province must be 2 characters (e.g., ON, BC, QC)'
    })
    postal_code = serializers.CharField(max_length=10, min_length=1, error_messages={
        'required': 'Postal code is required',
        'min_length': 'Postal code cannot be empty'
    })

    def validate_province(self, value):
        """Ensure province is uppercase 2-letter code"""
        if len(value) != 2:
            raise serializers.ValidationError("Province must be exactly 2 characters (e.g., ON, BC, QC)")
        return value.upper()

    def validate_postal_code(self, value):
        """Basic validation for Canadian postal code format"""
        import re
        # Remove spaces and convert to uppercase
        cleaned = value.replace(' ', '').upper()
        # Canadian postal code pattern: A1A 1A1 (letter-digit-letter digit-letter-digit)
        if not re.match(r'^[A-Z]\d[A-Z]\d[A-Z]\d$', cleaned):
            raise serializers.ValidationError("Invalid Canadian postal code format (e.g., M5H 2N2)")
        # Return formatted version with space: A1A 1A1
        return f"{cleaned[:3]} {cleaned[3:]}"


class StudentCreateSerializer(serializers.Serializer):
    """Serializer for creating a student with billing contact in one operation"""
    # Student fields
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(max_length=15, required=False, allow_blank=True)
    assigned_teachers = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True
    )

    # Billing contact fields (optional - if not provided, use student's info)
    use_student_as_contact = serializers.BooleanField(default=False)
    billing_contact = BillingContactInputSerializer(required=False)

    def validate_email(self, value):
        """Check if email already exists"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists")
        return value

    def validate_assigned_teachers(self, value):
        """Validate teacher IDs exist and are active"""
        if value:
            teachers = User.objects.filter(
                id__in=value,
                user_type='teacher',
                is_active=True
            )
            if teachers.count() != len(value):
                raise serializers.ValidationError("One or more teacher IDs are invalid")
        return value

    def create(self, validated_data):
        """Create student and billing contact atomically"""
        from django.db import transaction

        # Extract nested data
        assigned_teacher_ids = validated_data.pop('assigned_teachers', [])
        use_student_as_contact = validated_data.pop('use_student_as_contact', False)
        billing_contact_data = validated_data.pop('billing_contact', None)

        # Get school from request context
        request = self.context.get('request')
        if not request or not hasattr(request.user, 'school'):
            raise serializers.ValidationError({
                'school': 'Unable to determine school from request'
            })
        school = request.user.school

        with transaction.atomic():
            # Create student user
            student = User.objects.create_user(
                email=validated_data['email'],
                first_name=validated_data['first_name'],
                last_name=validated_data['last_name'],
                phone_number=validated_data.get('phone_number', ''),
                user_type='student',
                school=school,  # Set school from request user
                is_approved=True  # Management-created students are auto-approved
            )

            # Assign teachers if provided
            if assigned_teacher_ids:
                student.assigned_teachers.set(assigned_teacher_ids)

            # Create billing contact
            if use_student_as_contact:
                # When using student as contact, require complete address info
                if not billing_contact_data:
                    raise serializers.ValidationError({
                        'billing_contact': 'Complete billing address is required when student is their own contact'
                    })
                # Use student info but with provided address
                BillableContact.objects.create(
                    student=student,
                    school=school,  # Set school
                    contact_type='self',
                    first_name=student.first_name,
                    last_name=student.last_name,
                    email=student.email,
                    phone=billing_contact_data['phone'],
                    street_address=billing_contact_data['street_address'],
                    city=billing_contact_data['city'],
                    province=billing_contact_data['province'],
                    postal_code=billing_contact_data['postal_code'],
                    is_primary=True
                )
            else:
                # Use provided billing contact (required)
                if not billing_contact_data:
                    raise serializers.ValidationError({
                        'billing_contact': 'Billing contact information is required'
                    })
                # Create directly - serializer validation already ensures all fields present
                BillableContact.objects.create(
                    student=student,
                    school=school,  # Set school
                    contact_type=billing_contact_data.get('contact_type', 'parent'),
                    first_name=billing_contact_data['first_name'],
                    last_name=billing_contact_data['last_name'],
                    email=billing_contact_data['email'],
                    phone=billing_contact_data['phone'],
                    street_address=billing_contact_data['street_address'],
                    city=billing_contact_data['city'],
                    province=billing_contact_data['province'],
                    postal_code=billing_contact_data['postal_code'],
                    is_primary=True
                )

        return student
