from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    Lesson, Invoice, ApprovedEmail, UserRegistrationRequest,
    SystemSettings, InvoiceRecipientEmail, Student, BillableContact
)

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'user_type',
            'phone_number', 'address', 'city', 'province_state',
            'postal_code', 'country', 'is_approved', 'bio',
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

# Student Management Serializers

class BillableContactSerializer(serializers.ModelSerializer):
    """Serializer for billable contacts (parents/guardians)"""
    contact_type_display = serializers.CharField(source='get_contact_type_display', read_only=True)
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    full_address = serializers.CharField(source='get_full_address', read_only=True)

    class Meta:
        model = BillableContact
        fields = [
            'id', 'student', 'contact_type', 'contact_type_display',
            'relationship_notes', 'first_name', 'last_name', 'full_name',
            'email', 'phone', 'address_line1', 'address_line2',
            'city', 'province_state', 'postal_code', 'country',
            'full_address', 'payment_preferences', 'is_primary',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate(self, data):
        """Ensure at least one billable contact is primary per student"""
        student = data.get('student')
        is_primary = data.get('is_primary', False)

        # If this is the first contact for a student, it must be primary
        if student and not self.instance:
            existing_contacts = BillableContact.objects.filter(student=student)
            if not existing_contacts.exists() and not is_primary:
                raise serializers.ValidationError(
                    "The first billable contact must be set as primary"
                )

        return data


class NewStudentSerializer(serializers.ModelSerializer):
    """Basic serializer for Student model (list view)"""
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    age = serializers.IntegerField(read_only=True)
    assigned_teacher_names = serializers.SerializerMethodField()
    primary_contact = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            'id', 'first_name', 'last_name', 'full_name',
            'email', 'phone', 'date_of_birth', 'age', 'notes',
            'is_active', 'assigned_teacher_names', 'primary_contact',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_assigned_teacher_names(self, obj):
        return [teacher.get_full_name() for teacher in obj.assigned_teachers.all()]

    def get_primary_contact(self, obj):
        primary = obj.primary_billable_contact
        if primary:
            return {
                'id': primary.id,
                'name': primary.get_full_name(),
                'email': primary.email,
                'phone': primary.phone
            }
        return None


class StudentDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for Student model (detail view with nested data)"""
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    age = serializers.IntegerField(read_only=True)
    assigned_teachers = UserSerializer(many=True, read_only=True)
    billable_contacts = BillableContactSerializer(many=True, read_only=True)
    lesson_count = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            'id', 'first_name', 'last_name', 'full_name',
            'email', 'phone', 'date_of_birth', 'age', 'notes',
            'is_active', 'assigned_teachers', 'billable_contacts',
            'lesson_count', 'user_account', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_lesson_count(self, obj):
        return obj.lessons.count()


class TeacherStudentSerializer(serializers.ModelSerializer):
    """Simplified serializer for teachers' assigned students (for invoice dropdown)"""
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    primary_billable_contact = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = ['id', 'full_name', 'primary_billable_contact']

    def get_primary_billable_contact(self, obj):
        primary = obj.primary_billable_contact
        if primary:
            return BillableContactSerializer(primary).data
        return None


# Legacy serializers for backward compatibility (deprecated - keep for now)
class TeacherSerializer(serializers.ModelSerializer):
    """Legacy serializer - use UserSerializer instead"""
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'bio', 'instruments', 'hourly_rate', 'phone_number', 'address']


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