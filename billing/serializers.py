from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum, Q
from .models import Lesson, Invoice, ApprovedEmail, UserRegistrationRequest, SystemSettings, InvoiceRecipientEmail, GlobalRateSettings

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'user_type',
            'phone_number', 'address', 'is_approved', 'bio', 
            'instruments', 'hourly_rate', 'assigned_teacher',
            'parent_email', 'parent_phone', 'password'
        ]
        extra_kwargs = {'password': {'write_only': True}}
    
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
    total_cost = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = Lesson
        fields = '__all__'

class InvoiceSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source='teacher.get_full_name', read_only=True)
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)
    
    class Meta:
        model = Invoice
        fields = '__all__'


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
    assigned_teacher_name = serializers.CharField(source='assigned_teacher.get_full_name', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'user_type', 'user_type_display',
            'phone_number', 'address', 'is_approved', 'oauth_provider', 'oauth_id',
            'bio', 'instruments', 'hourly_rate', 'assigned_teacher', 'assigned_teacher_name',
            'parent_email', 'parent_phone', 'date_joined', 'last_login'
        ]
        read_only_fields = ['date_joined', 'last_login']


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

    class Meta:
        model = InvoiceRecipientEmail
        fields = ['id', 'email', 'created_at', 'created_by', 'created_by_name']
        read_only_fields = ['id', 'created_at', 'created_by', 'created_by_name']


# Step 2: Dual-Rate System Serializers

class GlobalRateSettingsSerializer(serializers.ModelSerializer):
    """Serializer for global rate settings (singleton)"""
    updated_by_name = serializers.CharField(source='updated_by.get_full_name', read_only=True)

    class Meta:
        model = GlobalRateSettings
        fields = [
            'id', 'online_teacher_rate', 'online_student_rate', 'inperson_student_rate',
            'updated_at', 'updated_by', 'updated_by_name'
        ]
        read_only_fields = ['id', 'updated_at', 'updated_by', 'updated_by_name']


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