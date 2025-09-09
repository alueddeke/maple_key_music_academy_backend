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
]