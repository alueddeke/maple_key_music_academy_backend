from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Lesson, Invoice, ApprovedEmail, UserRegistrationRequest

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

# Legacy serializers for backward compatibility (deprecated)
class TeacherSerializer(serializers.ModelSerializer):
    """Legacy serializer - use UserSerializer instead"""
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'bio', 'instruments', 'hourly_rate', 'phone_number', 'address']

class StudentSerializer(serializers.ModelSerializer):
    """Legacy serializer - use UserSerializer instead"""
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'phone_number', 'address', 'assigned_teacher', 'parent_email', 'parent_phone']


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