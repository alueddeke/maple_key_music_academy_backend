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

    # Management endpoints for invoice management
    path('management/invoices/', views.management_all_invoices, name='management_all_invoices'),
    path('management/invoices/<int:pk>/update/', views.management_update_invoice, name='management_update_invoice'),
    path('management/invoices/<int:pk>/status/', views.management_update_invoice_status, name='management_update_invoice_status'),
    path('management/invoices/<int:pk>/recalculate/', views.management_recalculate_invoice, name='management_recalculate_invoice'),
    path('management/invoices/<int:pk>/regenerate-pdf/', views.management_regenerate_invoice_pdf, name='management_regenerate_invoice_pdf'),
]