from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from .models import (
    Lesson,
    Invoice,
    ApprovedEmail,
    UserRegistrationRequest,
    InvitationToken,
    School,
    SchoolSettings,
    MonthlyInvoiceBatch,
    StudentInvoice,
    StudentCreditAccount,
    CreditTransaction,
    HelcimWebhookEvent,
    PreBillingInvoice,
    InvoiceRecipientEmail,
)
from .services.webhook_processing import process_webhook_event, RETRYABLE_STATES

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
        ('Student fields', {'fields': ('assigned_teachers',)}),
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
    list_display = ('student', 'teacher', 'scheduled_date', 'lesson_type', 'status', 'total_cost')
    list_filter = ('status', 'lesson_type', 'teacher', 'created_at')
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

@admin.register(ApprovedEmail)
class ApprovedEmailAdmin(admin.ModelAdmin):
    list_display = ('email', 'user_type', 'approved_by', 'approved_at')
    list_filter = ('user_type', 'approved_at')
    search_fields = ('email',)

@admin.register(UserRegistrationRequest)
class UserRegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'user_type', 'status', 'requested_at')
    list_filter = ('status', 'user_type', 'requested_at')
    search_fields = ('email', 'first_name', 'last_name')

# ---------------------------------------------------------------------------
# Billing / payment ops — the admin is the recovery tool for stuck payments:
# a HelcimWebhookEvent in a retryable state can be re-processed from here
# without shell access.
# ---------------------------------------------------------------------------

@admin.register(HelcimWebhookEvent)
class HelcimWebhookEventAdmin(admin.ModelAdmin):
    list_display = ('helcim_transaction_id', 'invoice_id', 'amount',
                    'transaction_status', 'transaction_type',
                    'processing_status', 'school', 'received_at')
    list_filter = ('processing_status', 'transaction_status', 'transaction_type', 'school')
    search_fields = ('helcim_transaction_id', 'invoice_id')
    readonly_fields = ('helcim_transaction_id', 'raw_payload', 'invoice_id', 'amount',
                       'transaction_status', 'transaction_type', 'processing_status',
                       'last_error', 'processed_at', 'received_at', 'school')
    actions = ['retry_processing']

    @admin.action(description='Retry credit reconciliation (retryable states only)')
    def retry_processing(self, request, queryset):
        retried = skipped = 0
        for event in queryset:
            if event.processing_status in RETRYABLE_STATES:
                process_webhook_event(event)
                retried += 1
            else:
                skipped += 1
        self.message_user(
            request,
            f'{retried} event(s) re-processed, {skipped} skipped (terminal state).',
        )

    def has_add_permission(self, request):
        return False  # events come only from Helcim

    def has_delete_permission(self, request, obj=None):
        return False  # audit trail — never delete payment events


@admin.register(PreBillingInvoice)
class PreBillingInvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'school', 'status', 'amount',
                    'period_start', 'helcim_invoice_number', 'email_sent', 'updated_at')
    list_filter = ('status', 'email_sent', 'school', 'period_start')
    search_fields = ('student__email', 'student__first_name', 'student__last_name',
                     'helcim_invoice_number', 'helcim_invoice_id')
    readonly_fields = ('helcim_invoice_id', 'helcim_invoice_number', 'payment_token',
                       'created_at', 'updated_at')


@admin.register(StudentCreditAccount)
class StudentCreditAccountAdmin(admin.ModelAdmin):
    list_display = ('student', 'school', 'balance', 'created_at')
    list_filter = ('school',)
    search_fields = ('student__email', 'student__first_name', 'student__last_name')


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ('account', 'school', 'type', 'amount', 'created_at')
    list_filter = ('type', 'school')
    search_fields = ('account__student__email', 'account__student__first_name',
                     'account__student__last_name')
    readonly_fields = ('account', 'school', 'type', 'amount', 'created_at')

    def has_add_permission(self, request):
        return False  # immutable ledger — entries come from billing flows only

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MonthlyInvoiceBatch)
class MonthlyInvoiceBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'teacher', 'school', 'month', 'year', 'status', 'reviewed_at')
    list_filter = ('status', 'school', 'year', 'month')
    search_fields = ('teacher__email', 'teacher__first_name', 'teacher__last_name')


@admin.register(StudentInvoice)
class StudentInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'student', 'batch', 'amount', 'credit_applied',
                    'amount_after_credit')
    search_fields = ('invoice_number', 'student__email', 'student__first_name',
                     'student__last_name')


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ('name', 'subdomain', 'email', 'is_active')
    search_fields = ('name', 'subdomain')


@admin.register(SchoolSettings)
class SchoolSettingsAdmin(admin.ModelAdmin):
    list_display = ('school', 'waive_limit_enabled', 'waive_limit', 'updated_at')


@admin.register(InvoiceRecipientEmail)
class InvoiceRecipientEmailAdmin(admin.ModelAdmin):
    list_display = ('email', 'school', 'created_at')
    list_filter = ('school',)
    search_fields = ('email',)


@admin.register(InvitationToken)
class InvitationTokenAdmin(admin.ModelAdmin):
    list_display = ('email', 'user_type', 'is_used', 'is_token_valid', 'created_at', 'expires_at')
    list_filter = ('is_used', 'user_type', 'created_at')
    search_fields = ('email', 'token')
    readonly_fields = ('token', 'created_at', 'used_at')

    def is_token_valid(self, obj):
        return obj.is_valid()
    is_token_valid.boolean = True
    is_token_valid.short_description = 'Valid'