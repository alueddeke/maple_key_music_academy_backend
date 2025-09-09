from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from .models import Lesson, Invoice

#manages admin interface

User = get_user_model()

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'user_type', 'is_approved', 'is_staff')
    list_filter = ('user_type', 'is_approved', 'is_staff', 'is_active')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'phone_number', 'address')}),
        ('Role & Status', {'fields': ('user_type', 'is_approved', 'oauth_provider')}),
        ('Teacher fields', {'fields': ('bio', 'instruments', 'hourly_rate')}),
        ('Student fields', {'fields': ('assigned_teacher', 'parent_email', 'parent_phone')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'user_type', 'password1', 'password2'),
        }),
    )

@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('student', 'teacher', 'scheduled_date', 'status', 'total_cost')
    list_filter = ('status', 'teacher', 'created_at')
    search_fields = ('student__email', 'teacher__email')

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_type', 'get_recipient', 'payment_balance', 'status', 'created_at')
    list_filter = ('invoice_type', 'status', 'created_at')
    
    def get_recipient(self, obj):
        if obj.teacher:
            return obj.teacher.get_full_name()
        elif obj.student:
            return obj.student.get_full_name()
        return "Unknown"
    get_recipient.short_description = 'Recipient'