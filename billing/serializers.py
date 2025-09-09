from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Lesson, Invoice

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