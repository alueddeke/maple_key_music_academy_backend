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
