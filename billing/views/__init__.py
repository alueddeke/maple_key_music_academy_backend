# billing/views/__init__.py
# Re-export all public view functions so that billing/urls.py can continue
# to use `from . import views` and `views.function_name` without any change.

from .management import (
    teacher_list,
    all_teachers,
    approve_teacher,
    student_list,
    approved_email_list,
    approved_email_delete,
    registration_request_list,
    approve_registration_request,
    reject_registration_request,
    management_all_users,
    management_delete_user,
    management_all_invoices,
    management_update_invoice,
    management_update_invoice_status,
    management_recalculate_invoice,
    management_reject_invoice,
    get_system_settings,
    update_system_settings,
    list_invoice_recipients,
    add_invoice_recipient,
    delete_invoice_recipient,
    school_settings,
    teacher_list_with_stats,
    teacher_detail,
    management_students,
    management_student_detail,
    add_billable_contact,
    manage_billable_contact,
    student_recurring_schedules,
    recurring_schedule_detail,
    student_pause_lessons,
    assign_teachers_to_student,
    unassign_teacher_from_student,
    teacher_students,
    management_update_teacher,
    management_delete_teacher,
    get_current_school,
    update_school,
    management_pending_batches,
    management_approved_batches,
    management_rejected_batches,
    management_batch_detail,
    management_edit_lesson_notes,
    management_approve_batch,
    management_reject_batch,
    management_batch_rejection_snapshots,
    waive_policy_settings,
    management_delete_rejected_batch,
    management_archive_month,
    management_archived_batches,
    management_unarchive_batch,
    # Phase 21: Billing Dashboard (DASH-01 through DASH-04)
    management_dashboard_batches,
    management_dashboard_data,
    management_teacher_invoices,
    management_patch_invoice,
    management_upsert_expenses,
    management_expense_items,
    management_expense_item_delete,
    # Phase 22: Month-End Adjustments
    management_month_end_queue,
    management_generate_teacher_invoice,
)

from .teacher import (
    teacher_invoice_list,
    teacher_invoice_stats,
    submit_lessons_for_invoice,
    approve_teacher_invoice,
    teacher_assigned_students,
    teacher_monthly_batches,
    batch_detail,
    batch_add_lesson,
    batch_lesson_item,
    batch_submit,
    download_paystub,
    # Phase 22: Month-End Adjustments
    teacher_batch_adjustment_item,
    student_waive_usage,
)

from .lessons import (
    lesson_list,
    request_lesson,
    confirm_lesson,
    complete_lesson,
)

from .students import (
    student_detail,
    lesson_detail,
    invoice_detail,
)

from .invitation import (
    validate_invitation_token,
    setup_account_with_invitation,
)

from .webhooks import (
    payment_callback,
)

from .pre_billing import (
    management_pre_billing_generate,
    management_pre_billing_list,
    management_pre_billing_detail,
    management_pre_billing_send,
    management_pre_billing_send_all,
    management_pre_billing_remove_lesson,
)
