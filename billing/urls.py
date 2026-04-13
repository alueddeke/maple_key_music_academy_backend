from django.urls import path
from . import views

#function as endpoints for the billing app

urlpatterns = [
    # User management
    path('teachers/', views.teacher_list, name='teacher_list'),
    path('teachers/all/', views.all_teachers, name='all_teachers'),
    path('teachers/<int:teacher_id>/approve/', views.approve_teacher, name='approve_teacher'),
    path('students/', views.student_list, name='student_list'),
    
    # Lesson management  
    path('lessons/', views.lesson_list, name='lesson_list'),
    path('lessons/request/', views.request_lesson, name='request_lesson'),
    path('lessons/<int:lesson_id>/confirm/', views.confirm_lesson, name='confirm_lesson'),
    path('lessons/<int:lesson_id>/complete/', views.complete_lesson, name='complete_lesson'),
    
    # Invoice management
    path('invoices/teacher/', views.teacher_invoice_list, name='teacher_invoice_list'),
    path('invoices/teacher/stats/', views.teacher_invoice_stats, name='teacher_invoice_stats'),
    path('invoices/teacher/submit-lessons/', views.submit_lessons_for_invoice, name='submit_lessons_for_invoice'),
    path('invoices/teacher/<int:invoice_id>/approve/', views.approve_teacher_invoice, name='approve_teacher_invoice'),
    
    # Detail views (for backward compatibility)
    path('teachers/<int:pk>/', views.teacher_detail, name='teacher_detail'),
    path('students/<int:pk>/', views.student_detail, name='student_detail'),
    path('lessons/<int:pk>/', views.lesson_detail, name='lesson_detail'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),

    # Management endpoints for user approval system
    path('management/approved-emails/', views.approved_email_list, name='approved_email_list'),
    path('management/approved-emails/<int:pk>/', views.approved_email_delete, name='approved_email_delete'),
    path('management/registration-requests/', views.registration_request_list, name='registration_request_list'),
    path('management/registration-requests/<int:pk>/approve/', views.approve_registration_request, name='approve_registration_request'),
    path('management/registration-requests/<int:pk>/reject/', views.reject_registration_request, name='reject_registration_request'),
    path('management/users/', views.management_all_users, name='management_all_users'),
    path('management/users/<int:pk>/', views.management_delete_user, name='management_delete_user'),

    # Invitation token endpoints (public - no auth required)
    path('invite/<str:token>/validate/', views.validate_invitation_token, name='validate_invitation_token'),
    path('invite/<str:token>/setup/', views.setup_account_with_invitation, name='setup_account_with_invitation'),

    # Management endpoints for invoice management
    path('management/invoices/', views.management_all_invoices, name='management_all_invoices'),
    path('management/invoices/<int:pk>/update/', views.management_update_invoice, name='management_update_invoice'),
    path('management/invoices/<int:pk>/status/', views.management_update_invoice_status, name='management_update_invoice_status'),
    path('management/invoices/<int:pk>/recalculate/', views.management_recalculate_invoice, name='management_recalculate_invoice'),
    path('management/invoices/<int:pk>/reject/', views.management_reject_invoice, name='management_reject_invoice'),
    path('management/invoices/<int:pk>/regenerate-pdf/', views.management_regenerate_invoice_pdf, name='management_regenerate_invoice_pdf'),

    # Management endpoints for system settings
    path('management/settings/', views.get_system_settings, name='get_system_settings'),
    path('management/settings/update/', views.update_system_settings, name='update_system_settings'),

    # Management endpoints for invoice recipient emails
    path('management/invoice-recipients/', views.list_invoice_recipients, name='list_invoice_recipients'),
    path('management/invoice-recipients/add/', views.add_invoice_recipient, name='add_invoice_recipient'),
    path('management/invoice-recipients/<int:pk>/delete/', views.delete_invoice_recipient, name='delete_invoice_recipient'),

    # Step 2: Dual-Rate System Management Endpoints (DEPRECATED - use school endpoints)
    path('management/global-rates/', views.school_settings, name='global_rate_settings'),  # DEPRECATED: redirects to school settings
    path('management/teachers/', views.teacher_list_with_stats, name='management_teacher_list'),
    path('management/teachers/<int:pk>/', views.teacher_detail, name='management_teacher_detail'),

    # Phase 5: School Management Endpoints
    path('management/school/', views.get_current_school, name='get_current_school'),
    path('management/school/update/', views.update_school, name='update_school'),
    path('management/school/settings/', views.school_settings, name='school_settings'),

    # Student management endpoints (full CRUD)
    path('management/students/', views.management_students, name='management_students'),
    path('management/students/<int:pk>/', views.management_student_detail, name='management_student_detail'),

    # Billable contact endpoints
    path('management/students/<int:student_id>/billable-contacts/', views.add_billable_contact, name='add_billable_contact'),
    path('management/billable-contacts/<int:pk>/', views.manage_billable_contact, name='manage_billable_contact'),

    # Recurring lesson schedule endpoints
    path('management/students/<int:student_id>/schedules/', views.student_recurring_schedules, name='student_recurring_schedules'),
    path('management/students/<int:student_id>/schedules/<int:schedule_id>/', views.recurring_schedule_detail, name='recurring_schedule_detail'),

    # Teacher-student assignment endpoints
    path('management/students/<int:student_id>/assign-teachers/', views.assign_teachers_to_student, name='assign_teachers_to_student'),
    path('management/students/<int:student_id>/unassign-teacher/<int:teacher_id>/', views.unassign_teacher_from_student, name='unassign_teacher_from_student'),
    path('management/teachers/<int:teacher_id>/students/', views.teacher_students, name='teacher_students'),

    # Teacher management endpoints (update/delete only, no create)
    path('management/teachers/<int:pk>/update/', views.management_update_teacher, name='management_update_teacher'),
    path('management/teachers/<int:pk>/delete/', views.management_delete_teacher, name='management_delete_teacher'),

    # Teacher-specific endpoints
    path('teacher/students/', views.teacher_assigned_students, name='teacher_assigned_students'),

    # Monthly Invoice Batches (Teacher Workflow) - Phase 3
    path('teacher/batches/', views.teacher_monthly_batches, name='teacher_monthly_batches'),
    path('teacher/batches/<int:batch_id>/', views.batch_detail, name='batch_detail'),
    path('teacher/batches/<int:batch_id>/add-lesson/', views.batch_add_lesson, name='batch_add_lesson'),
    path('teacher/batches/<int:batch_id>/lessons/<int:item_id>/', views.batch_lesson_item, name='batch_lesson_item'),
    path('teacher/batches/<int:batch_id>/submit/', views.batch_submit, name='batch_submit'),
    path('teacher/batches/<int:batch_id>/paystub/', views.download_paystub, name='download_paystub'),

    # Management Batch Approval (Phase 7)
    path('management/batches/pending/', views.management_pending_batches, name='management_pending_batches'),
    path('management/batches/approved/', views.management_approved_batches, name='management_approved_batches'),
    path('management/batches/rejected/', views.management_rejected_batches, name='management_rejected_batches'),
    path('management/batches/<int:batch_id>/', views.management_batch_detail, name='management_batch_detail'),
    path('management/batches/<int:batch_id>/lessons/<int:item_id>/', views.management_edit_lesson_notes, name='management_edit_lesson_notes'),
    path('management/batches/<int:batch_id>/approve/', views.management_approve_batch, name='management_approve_batch'),
    path('management/batches/<int:batch_id>/reject/', views.management_reject_batch, name='management_reject_batch'),
]