# Django REST API Setup Guide - Music Academy Billing System

***IMPORTANT: When committing, make sure to exclude `__pycache__` and `SECRET_KEY`!***

This guide teaches you how to build a Django REST API using a real-world music academy billing system as an example. You'll learn how to create models, serializers, views, and endpoints for managing teachers, students, lessons, and invoices.

## Table of Contents
1. [Virtual Environment Setup](#1-virtual-environment-setup)
2. [Django Project Creation](#2-django-project-creation)
3. [Testing the Server](#3-testing-the-server)
4. [Django Project vs App Concept](#4-django-project-vs-app-concept)
5. [Creating Your First App](#5-creating-your-first-app)
6. [Database Setup](#6-database-setup)
7. [Project Configuration](#7-project-configuration)
8. [Creating Models](#8-creating-models)
9. [Django Admin Setup](#9-django-admin-setup)
10. [Creating Serializers](#10-creating-serializers)
11. [Creating Views](#11-creating-views)
12. [URL Configuration](#12-url-configuration)
13. [Testing Your API](#13-testing-your-api)
14. [Security Setup](#14-security-setup)

---

## 1. Virtual Environment Setup

Python projects need different versions of packages which can conflict. Creating a virtual environment per project ensures that everything in the project is using the same versions.

```bash
python -m venv venv           # Create a new "apartment" called 'venv'
source venv/bin/activate     # "Move into" that apartment (macOS/Linux)
# OR
venv\Scripts\activate        # "Move into" that apartment (Windows)
pip install django djangorestframework django-cors-headers  # Install packages
deactivate                   # "Leave" the apartment, back to system Python
```

**Packages Explained:**
- **django** - The main web framework
- **djangorestframework** - Makes building APIs easier
- **django-cors-headers** - Allows your frontend to talk to this backend

```bash
# Create requirements.txt to track dependencies
pip freeze > requirements.txt
```

---

## 2. Django Project Creation

```bash
django-admin startproject maple_key_backend .
```

**The `.` is important** - it creates the project in your current directory instead of making a new folder.

This creates:
```
maple_key_backend/
├── manage.py                    # Django's command-line utility
├── maple_key_backend/           # Project configuration directory
│   ├── __init__.py
│   ├── settings.py              # Project settings
│   ├── urls.py                  # Main URL configuration
│   ├── asgi.py                  # ASGI configuration
│   └── wsgi.py                  # WSGI configuration
└── requirements.txt
```

---

## 3. Testing the Server

```bash
python manage.py runserver
```

This will start the development server and give you a URL (usually `http://127.0.0.1:8000/`). Visit it to see Django's welcome page.

---

## 4. Django Project vs App Concept

**Django Project** = Your entire website/API  
**Django App** = A specific feature within your project

**For our Music Academy Billing System:**
- **Project**: `maple_key_backend` (the whole API)
- **App**: `billing` (the billing feature - teachers, students, lessons, invoices)


---

## 5. Creating Your First App

```bash
python manage.py startapp billing
```

This creates:
```
billing/
├── __init__.py
├── admin.py              # Django admin interface configuration
├── apps.py               # App configuration
├── models.py             # Database structure (tables)
├── views.py              # API logic (what happens when someone visits a URL)
├── tests.py              # Tests for your app
└── migrations/           # Database change files
```

---

## 6. Database Setup

```bash
# Run initial migrations
python manage.py migrate
```

This creates your first migrations and comes with built-in apps like auth, admin, contenttypes, sessions. It creates tables like:
- `auth_user` (for user accounts)
- `auth_group` (for user groups)
- `django_admin_log` (admin actions)
- `django_session` (user sessions)

**Create superuser (for testing and admin access):**
```bash
python manage.py createsuperuser
```
This creates an admin user with access to everything - used for testing and easy database/user management.

---

## 7. Project Configuration

Configure your project in `maple_key_backend/settings.py`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',        # Add this for API functionality
    'corsheaders',          # Add this for frontend communication
    'billing',              # Add this (your app)
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Add this at the top
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

At the bottom of settings.py, add:

```python
# Allow your frontend to connect
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
]

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
}
```

---

## 8. Creating Models

Models define your database structure. Think of them as blueprints for your database tables.

In `billing/models.py`:

```python
from django.db import models

class Teacher(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=255)
    address = models.CharField(max_length=225)
    phoneNumber = models.CharField(max_length=11)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name

class Student(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    name = models.CharField(max_length=225)
    email = models.EmailField(max_length=255)
    address = models.CharField(max_length=225)
    phoneNumber = models.CharField(max_length=11)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name

class Lesson(models.Model):
    rate = models.DecimalField(max_digits=6, decimal_places=2, default=80.00)
    date = models.DateTimeField()
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    duration = models.DecimalField(max_digits=4, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def total_cost(self):
        return self.rate * self.duration
    
    def __str__(self):
        return f"{self.student.name} - {self.date}"

class Invoice(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('paid', 'Paid'), ('overdue', 'Overdue')]
    lessons = models.ManyToManyField(Lesson)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    paymentBalance = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=255, choices=STATUS_CHOICES, default='pending')
    date = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def calculate_payment_balance(self):
        total = 0
        for lesson in self.lessons.all():
            total += lesson.total_cost()
        return total
    
    def save(self, *args, **kwargs):
        self.paymentBalance = self.calculate_payment_balance()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.teacher.name} - {self.date} - {self.paymentBalance}"
```

**Model Relationships Explained:**
- **ForeignKey**: "One-to-Many" relationship (one teacher can have many students)
- **ManyToManyField**: "Many-to-Many" relationship (one invoice can have many lessons, one lesson can be in many invoices)
- **CharField**: Text field with max length
- **EmailField**: Email validation
- **DecimalField**: Decimal numbers (for money)
- **DateTimeField**: Date and time
- **auto_now_add=True**: Automatically set when object is created

**Create and apply migrations:**
```bash
python manage.py makemigrations
python manage.py migrate
```

---

## 9. Django Admin Setup

Django admin automatically creates forms to manage data. This is where you register your models to make them accessible through the web interface.

In `billing/admin.py`:

```python
from django.contrib import admin
from .models import Teacher, Student, Lesson, Invoice

admin.site.register(Teacher)
admin.site.register(Student)
admin.site.register(Lesson)
admin.site.register(Invoice)
```

Now you can:
1. Run the server: `python manage.py runserver`
2. Visit: `http://127.0.0.1:8000/admin/`
3. Login with your superuser credentials
4. Create test data for teachers, students, lessons, and invoices

---

## 10. Creating Serializers

Serializers convert your Django models to JSON (and vice versa). Think of them as translators between your database and the API.

Create `billing/serializers.py`:

```python
from rest_framework import serializers
from .models import Teacher, Student, Lesson, Invoice

class TeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = Teacher
        fields = '__all__'  # Include all fields

class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = '__all__'

class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = '__all__'

class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = '__all__'
```

**Serializer Explained:**
- **ModelSerializer**: Automatically creates serializers based on your models
- **fields = '__all__'**: Include all model fields in the API
- **Meta class**: Configuration for the serializer

---

## 11. Creating Views

Views handle HTTP requests. They define what happens when someone visits a URL.

In `billing/views.py`:

```python
from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Invoice, Lesson, Student, Teacher
from .serializers import InvoiceSerializer, LessonSerializer, StudentSerializer, TeacherSerializer

# LIST OBJECTS (GET all, POST new)

@api_view(['GET', 'POST'])
def teacher_list(request):
    if request.method == 'GET':
        teachers = Teacher.objects.all()
        serializer = TeacherSerializer(teachers, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = TeacherSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'POST'])
def student_list(request):
    if request.method == 'GET':
        students = Student.objects.all()
        serializer = StudentSerializer(students, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = StudentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'POST'])
def lesson_list(request):
    if request.method == 'GET':
        lessons = Lesson.objects.all()
        serializer = LessonSerializer(lessons, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = LessonSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'POST'])
def invoice_list(request):
    if request.method == 'GET':
        invoices = Invoice.objects.all()
        serializer = InvoiceSerializer(invoices, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = InvoiceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# INDIVIDUAL/DETAIL OBJECTS (GET one, PUT update, DELETE)

@api_view(['GET', 'PUT', 'DELETE'])
def teacher_detail(request, pk):
    try:
        teacher = Teacher.objects.get(pk=pk)
    except Teacher.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    
    if request.method == 'GET':
        serializer = TeacherSerializer(teacher)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        serializer = TeacherSerializer(teacher, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        teacher.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

# Similar detail views for student, lesson, and invoice...
```

**View Concepts Explained:**
- **@api_view**: Decorator that adds API functionality to your function
- **request.method**: Determines if it's GET, POST, PUT, or DELETE
- **serializer.data**: Converts model to JSON
- **serializer.is_valid()**: Checks if the data is correct
- **status codes**: HTTP status codes (200=OK, 201=Created, 400=Bad Request, 404=Not Found)

---

## 12. URL Configuration

URLs route requests to views. Think of them as a receptionist directing visitors.

**App-level URLs** (`billing/urls.py`):
```python
from django.urls import path
from . import views

urlpatterns = [
    # List endpoints (GET all, POST new)
    path('teachers/', views.teacher_list, name='teacher_list'),
    path('students/', views.student_list, name='student_list'),
    path('lessons/', views.lesson_list, name='lesson_list'),
    path('invoices/', views.invoice_list, name='invoice_list'),
    
    # Detail endpoints (GET one, PUT update, DELETE)
    path('teachers/<int:pk>/', views.teacher_detail, name='teacher_detail'),
    path('students/<int:pk>/', views.student_detail, name='student_detail'),
    path('lessons/<int:pk>/', views.lesson_detail, name='lesson_detail'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
]
```

**Project-level URLs** (`maple_key_backend/urls.py`):
```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),           # Django admin interface
    path('api/billing/', include('billing.urls')),  # Your billing API
]
```

**URL Flow Explained:**
When someone visits `http://127.0.0.1:8000/api/billing/teachers/`:
1. Django checks project URLs → finds `/api/billing/`
2. Django strips `/api/billing/` and looks at app URLs → finds `/teachers/`
3. Django calls `views.teacher_list` function
4. Function returns JSON response

---

## 13. Testing Your API

**Start the server:**
```bash
python manage.py runserver
```

**Test your endpoints:**

1. **Get all teachers:**
   ```
   GET http://127.0.0.1:8000/api/billing/teachers/
   ```

2. **Create a new teacher:**
   ```
   POST http://127.0.0.1:8000/api/billing/teachers/
   Content-Type: application/json
   
   {
     "name": "John Smith",
     "email": "john@musicacademy.com",
     "address": "123 Music St",
     "phoneNumber": "555-0123"
   }
   ```

3. **Get a specific teacher:**
   ```
   GET http://127.0.0.1:8000/api/billing/teachers/1/
   ```

4. **Update a teacher:**
   ```
   PUT http://127.0.0.1:8000/api/billing/teachers/1/
   Content-Type: application/json
   
   {
     "name": "John Smith",
     "email": "john.updated@musicacademy.com",
     "address": "456 New Music St",
     "phoneNumber": "555-0123"
   }
   ```

5. **Delete a teacher:**
   ```
   DELETE http://127.0.0.1:8000/api/billing/teachers/1/
   ```

**Tools for testing:**
- **Browser**: For GET requests
- **Postman**: For all HTTP methods
- **curl**: Command line tool
- **Django Admin**: For creating test data

---

## 14. Security Setup

**Move secret key to environment variables:**

1. **Install python-decouple:**
   ```bash
   pip install python-decouple
   ```

2. **Create .env file:**
   ```bash
   touch .env
   ```

3. **Add to .env:**
   ```
   SECRET_KEY = "your-secret-key-here"
   DEBUG = True
   ```

4. **Update settings.py:**
   ```python
   from decouple import config
   
   SECRET_KEY = config('SECRET_KEY')
   DEBUG = config('DEBUG', default=False, cast=bool)
   ```

5. **Add .env to .gitignore:**
   ```
   # .gitignore
   .env
   __pycache__/
   *.pyc
   db.sqlite3
   ```

---

## Development Order Summary

1. **Admin first** - Easy way to create test data
   - Django admin automatically creates forms to manage data
   - Register your models to make them accessible through web interface
   - Helps you manage your tables

2. **Serializers** - Convert models to JSON
   - Translate your data structures to JSON so they can be read/written properly from API
   - Bridge between database and API

3. **Views** - Handle HTTP requests
   - Define what happens for each request to API
   - Business logic lives here

4. **URLs** - Route requests to views
   - Register your view configurations
   - Create both list and detail URLs

5. **Test** - Visit the URL and see if you get your expected response
   - Use browser, Postman, or curl to test endpoints
   - Verify data creation, retrieval, updates, and deletion

---

## API Endpoints Summary

Your music academy billing API now has these endpoints:

### Authentication Endpoints

**Google OAuth:**
- `GET /api/auth/google/` - Initiate Google OAuth login
- `GET /api/auth/google/callback/` - Google OAuth callback (handles authentication)

**JWT Token Management:**
- `POST /api/auth/token/` - Get JWT tokens (to be implemented)
- `POST /api/auth/token/refresh/` - Refresh JWT token (to be implemented)
- `GET /api/auth/user/` - Get current user profile (to be implemented)
- `POST /api/auth/logout/` - Logout user (to be implemented)

### Billing Endpoints

**Teachers:**
- `GET /api/billing/teachers/` - Get all teachers
- `POST /api/billing/teachers/` - Create new teacher
- `GET /api/billing/teachers/{id}/` - Get specific teacher
- `PUT /api/billing/teachers/{id}/` - Update teacher
- `DELETE /api/billing/teachers/{id}/` - Delete teacher

**Students:**
- `GET /api/billing/students/` - Get all students
- `POST /api/billing/students/` - Create new student
- `GET /api/billing/students/{id}/` - Get specific student
- `PUT /api/billing/students/{id}/` - Update student
- `DELETE /api/billing/students/{id}/` - Delete student

**Lessons:**
- `GET /api/billing/lessons/` - Get all lessons
- `POST /api/billing/lessons/` - Create new lesson
- `GET /api/billing/lessons/{id}/` - Get specific lesson
- `PUT /api/billing/lessons/{id}/` - Update lesson
- `DELETE /api/billing/lessons/{id}/` - Delete lesson

**Invoices:**
- `GET /api/billing/invoices/` - Get all invoices
- `POST /api/billing/invoices/` - Create new invoice
- `GET /api/billing/invoices/{id}/` - Get specific invoice
- `PUT /api/billing/invoices/{id}/` - Update invoice
- `DELETE /api/billing/invoices/{id}/` - Delete invoice

### Authentication Flow

1. **Frontend redirects user to:** `GET /api/auth/google/`
2. **User authenticates with Google**
3. **Google redirects to:** `GET /api/auth/google/callback/?code=...`
4. **Backend processes OAuth and returns:**
   ```json
   {
     "message": "OAuth successful",
     "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
     "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
     "user": {
       "email": "teacher@example.com",
       "name": "John Smith",
       "teacher_id": 1
     }
   }
   ```
5. **Frontend uses `access_token` for authenticated API calls**
6. **When token expires, use `refresh_token` to get new `access_token`**


