from django.urls import path
from . import views

urlpatterns = [
    # LIST OBJECTS
    path('teachers/', views.teacher_list, name='teacher-list'),
    path('students/', views.student_list, name='student-list'),
    path('lessons/', views.lesson_list, name='lesson-list'),
    path('invoices/', views.invoice_list, name='invoice-list'),


# INDIVIDUAL/DETAIL OBJECTS
# <int:pk> data type is integer and primary key is named pk
#teacher/1/ -> teacher_detail(request, pk=1) fetches teacher with id 1
    path('teachers/<int:pk>/', views.teacher_detail, name='teacher-detail'),
    path('students/<int:pk>/', views.student_detail, name='student-detail'),
    path('lessons/<int:pk>/', views.lesson_detail, name='lesson-detail'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice-detail'),
]