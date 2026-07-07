from django.contrib import admin

from .models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'type', 'message', 'read_status', 'created_at')
    list_filter = ('type', 'read_status')
    search_fields = ('user__email', 'message')


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'email_enabled', 'sms_enabled', 'updated_at')
    list_filter = ('email_enabled', 'sms_enabled')
    search_fields = ('user__email',)
