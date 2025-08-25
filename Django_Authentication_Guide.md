# Django Authentication Complete Guide

***A comprehensive tutorial for implementing authentication in Django with Google OAuth, JWT tokens, and traditional authentication***

## Table of Contents
1. [Understanding Authentication Types](#1-understanding-authentication-types)
2. [Why You Need Both OAuth and Traditional Auth](#2-why-you-need-both-oauth-and-traditional-auth)
3. [Setting Up Google OAuth](#3-setting-up-google-oauth)
4. [Implementing JWT Authentication](#4-implementing-jwt-authentication)
5. [Role-Based Permissions](#5-role-based-permissions)
6. [Frontend Integration](#6-frontend-integration)
7. [Troubleshooting Common Errors](#7-troubleshooting-common-errors)
8. [Suggested Commit Points](#8-suggested-commit-points)

---

## 1. Understanding Authentication Types

### **Traditional Django Authentication (Session-Based)**
- **How it works:** User logs in with username/password, Django creates a session
- **Use case:** Django Admin interface, server-side rendered pages
- **Pros:** Simple, built into Django, works with admin
- **Cons:** Requires sessions, not ideal for APIs

### **OAuth 2.0 (Google, Facebook, GitHub, etc.)**
- **How it works:** User authenticates with a third-party service (Google)
- **Use case:** Modern web apps, mobile apps, APIs
- **Pros:** No password management, trusted provider, better UX
- **Cons:** More complex setup, depends on third-party

### **JWT (JSON Web Tokens)**
- **How it works:** Stateless tokens that contain user information
- **Use case:** API authentication, single-page applications
- **Pros:** Stateless, scalable, works across domains
- **Cons:** Can't be revoked easily, tokens stored on client

---

## 2. Why You Need Both OAuth and Traditional Auth

### **The Problem:**
- **Django Admin** requires session authentication
- **Your API** needs JWT tokens for frontend
- **Different use cases** require different auth methods

### **The Solution:**
```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',  # For API
        'rest_framework.authentication.SessionAuthentication',        # For Admin
    ],
}
```

### **When Each is Used:**
- **Session Auth:** Django Admin (`/admin/`)
- **JWT Auth:** Your API endpoints (`/api/`)
- **OAuth:** User login flow (creates JWT tokens)

---

## 3. Setting Up Google OAuth

### **Step 1: Install Required Packages**

```bash
pip install django-allauth djangorestframework-simplejwt python-decouple requests cryptography
pip freeze > requirements.txt
```

**Good time to commit or test:** After installing packages

### **Step 2: Configure Django Settings**

```python
# settings.py
from decouple import config

# Security settings
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)

# Add to INSTALLED_APPS
INSTALLED_APPS = [
    # ... existing apps ...
    'django.contrib.sites',  # Required for allauth
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'custom_auth',  # Your auth app
]

# Site configuration
SITE_ID = 1

# Allauth settings
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',  # Traditional auth
    'allauth.account.auth_backends.AuthenticationBackend',  # OAuth auth
]

# Google OAuth settings
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': config('GOOGLE_CLIENT_ID'),
            'secret': config('GOOGLE_CLIENT_SECRET'),
            'key': ''
        },
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        }
    }
}

# REST Framework with JWT
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
}

# JWT settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# Allauth middleware
MIDDLEWARE = [
    # ... existing middleware ...
    'allauth.account.middleware.AccountMiddleware',
]
```

**Good time to commit or test:** After updating settings

### **Step 3: Create Environment Variables**

```bash
# .env file
SECRET_KEY=your-secret-key-here
DEBUG=True
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

### **Step 4: Set Up Google OAuth in Google Cloud Console**

1. **Go to:** https://console.cloud.google.com/
2. **Create a new project** or select existing
3. **Enable Google+ API** (or Google Identity API)
4. **Create OAuth 2.0 credentials:**
   - Application type: Web application
   - Authorized redirect URIs: `http://localhost:8000/api/auth/google/callback/`
5. **Copy Client ID and Client Secret**

### **Step 5: Create Authentication App**

```bash
python manage.py startapp custom_auth
```

### **Step 6: Create OAuth Views**

```python
# custom_auth/views.py
from django.shortcuts import redirect, render
from allauth.socialaccount.providers.google.views import oauth2_login, GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from allauth.socialaccount.providers.oauth2.views import OAuth2LoginView
from allauth.socialaccount.models import SocialLogin, SocialApp
from django.contrib.auth import get_user_model
from billing.models import Teacher
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
import requests

@api_view(['GET','POST'])
def google_oauth(request):
    """Initiate Google OAuth flow"""
    return oauth2_login(request, 'google')

@api_view(['GET'])
def google_oauth_callback(request):
    """Handle Google OAuth callback"""
    try:
        # Step 1: Get authorization code
        code = request.GET.get('code')
        if not code:
            return Response({'error': 'No authorization code provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Step 2: Get Google OAuth app configuration
        try:
            app = SocialApp.objects.get(provider='google')
        except SocialApp.DoesNotExist:
            return Response({'error': 'Google OAuth app not configured. Please set up in Django admin.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Step 3: Exchange code for tokens
        token_url = 'https://oauth2.googleapis.com/token'
        token_data = {
            'client_id': app.client_id,
            'client_secret': app.secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': 'http://localhost:8000/api/auth/google/callback/'
        }
        
        token_response = requests.post(token_url, data=token_data)
        if token_response.status_code != 200:
            return Response({'error': 'Failed to exchange code for token'}, status=status.HTTP_400_BAD_REQUEST)
        
        token_info = token_response.json()
        access_token = token_info.get('access_token')
        
        # Step 4: Get user info from Google
        user_info_url = 'https://www.googleapis.com/oauth2/v2/userinfo'
        headers = {'Authorization': f'Bearer {access_token}'}
        user_response = requests.get(user_info_url, headers=headers)
        
        if user_response.status_code != 200:
            return Response({'error': 'Failed to get user info from Google'}, status=status.HTTP_400_BAD_REQUEST)
        
        user_data = user_response.json()
        
        # Step 5: Create or get Django user
        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=user_data.get('email'),
            defaults={
                'username': user_data.get('email'),
                'first_name': user_data.get('given_name', ''),
                'last_name': user_data.get('family_name', ''),
            }
        )
        
        # Step 6: Create or get Teacher record
        teacher, teacher_created = Teacher.objects.get_or_create(
            email=user.email,
            defaults={
                'name': f"{user.first_name} {user.last_name}".strip() or user.email,
                'address': '',
                'phoneNumber': '',
            }
        )
        
        # Step 7: Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        # Get user name from Google data or use email as fallback
        user_name = f"{user.first_name} {user.last_name}".strip()
        if not user_name:
            user_name = user_data.get('name', user.email)
        
        return Response({
            'message': 'OAuth successful',
            'access_token': str(refresh.access_token),
            'refresh_token': str(refresh),
            'user': {
                'email': user.email,
                'name': user_name,
                'teacher_id': teacher.id
            }
        })
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
```

**Good time to commit or test:** After implementing OAuth views

### **Step 7: Configure URLs**

```python
# custom_auth/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('google/', views.google_oauth, name='google_oauth'),
    path('google/callback/', views.google_oauth_callback, name='google_callback'),
    path('token/', views.get_jwt_token, name='get_jwt_token'),
    path('token/refresh/', views.refresh_jwt_token, name='refresh_jwt_token'),
    path('user/', views.user_profile, name='user_profile'),
    path('logout/', views.logout, name='logout'),
]
```

```python
# maple_key_backend/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/billing/', include('billing.urls')),
    path('api/auth/', include('custom_auth.urls')),
]
```

### **Step 8: Set Up Social Application in Django Admin**

1. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

2. **Create superuser:**
   ```bash
   python manage.py createsuperuser
   ```

3. **Go to Django Admin:** `http://localhost:8000/admin/`

4. **Add Social Application:**
   - Provider: Google
   - Name: Google OAuth
   - Client ID: Your Google Client ID
   - Secret Key: Your Google Client Secret
   - Sites: Add your site (localhost:8000)

**Good time to commit or test:** After setting up admin configuration

---

## 4. Implementing JWT Authentication

### **JWT Token Endpoints**

```python
# custom_auth/views.py (add these functions)

@api_view(['POST'])
def get_jwt_token(request):
    """Get JWT token for traditional login"""
    from rest_framework_simplejwt.views import TokenObtainPairView
    from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
    
    serializer = TokenObtainPairSerializer(data=request.data)
    if serializer.is_valid():
        return Response(serializer.validated_data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
def refresh_jwt_token(request):
    """Refresh JWT token"""
    from rest_framework_simplejwt.views import TokenRefreshView
    from rest_framework_simplejwt.serializers import TokenRefreshSerializer
    
    serializer = TokenRefreshSerializer(data=request.data)
    if serializer.is_valid():
        return Response(serializer.validated_data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def user_profile(request):
    """Get current user profile"""
    from rest_framework.permissions import IsAuthenticated
    from rest_framework.decorators import permission_classes
    
    if not request.user.is_authenticated:
        return Response({'error': 'Not authenticated'}, status=status.HTTP_401_UNAUTHORIZED)
    
    try:
        teacher = Teacher.objects.get(email=request.user.email)
        return Response({
            'email': request.user.email,
            'name': f"{request.user.first_name} {request.user.last_name}".strip(),
            'teacher_id': teacher.id
        })
    except Teacher.DoesNotExist:
        return Response({'error': 'Teacher profile not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
def logout(request):
    """Logout user (invalidate tokens)"""
    # In a real implementation, you might want to blacklist the token
    return Response({'message': 'Logged out successfully'})
```

### **Using JWT Tokens in API Calls**

```python
# Example: Protected view that requires authentication
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def teacher_dashboard(request):
    """Only authenticated teachers can access"""
    teacher = Teacher.objects.get(email=request.user.email)
    # Your dashboard logic here
    return Response({'message': f'Welcome {teacher.name}!'})
```

---

## 5. Role-Based Permissions

### **Creating Custom Permissions**

```python
# billing/permissions.py
from rest_framework import permissions

class IsTeacher(permissions.BasePermission):
    """Allow access only to teachers"""
    
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        
        try:
            teacher = Teacher.objects.get(email=request.user.email)
            return True
        except Teacher.DoesNotExist:
            return False

class IsTeacherOwner(permissions.BasePermission):
    """Allow access only to the teacher who owns the resource"""
    
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        
        try:
            teacher = Teacher.objects.get(email=request.user.email)
            # Check if the object belongs to this teacher
            return obj.teacher == teacher
        except Teacher.DoesNotExist:
            return False
```

### **Using Permissions in Views**

```python
# billing/views.py
from .permissions import IsTeacher, IsTeacherOwner

@api_view(['GET', 'POST'])
@permission_classes([IsTeacher])
def teacher_invoices(request):
    """Only teachers can access their invoices"""
    if request.method == 'GET':
        teacher = Teacher.objects.get(email=request.user.email)
        invoices = Invoice.objects.filter(teacher=teacher)
        serializer = InvoiceSerializer(invoices, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        # Create new invoice for the authenticated teacher
        teacher = Teacher.objects.get(email=request.user.email)
        serializer = InvoiceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(teacher=teacher)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsTeacherOwner])
def invoice_detail(request, pk):
    """Only the teacher who owns the invoice can access it"""
    try:
        invoice = Invoice.objects.get(pk=pk)
    except Invoice.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    
    # The IsTeacherOwner permission will check if request.user owns this invoice
    if request.method == 'GET':
        serializer = InvoiceSerializer(invoice)
        return Response(serializer.data)
    
    elif request.method == 'PUT':
        serializer = InvoiceSerializer(invoice, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    elif request.method == 'DELETE':
        invoice.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
```

### **Student-Specific Permissions**

```python
# billing/permissions.py
class IsStudentOrTeacher(permissions.BasePermission):
    """Allow access to students and their teachers"""
    
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        
        # Teachers can access everything
        try:
            Teacher.objects.get(email=request.user.email)
            return True
        except Teacher.DoesNotExist:
            pass
        
        # Students can only access their own data
        try:
            Student.objects.get(email=request.user.email)
            return True
        except Student.DoesNotExist:
            return False

class IsStudentOwner(permissions.BasePermission):
    """Allow access only to the student who owns the resource"""
    
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        
        # Teachers can access everything
        try:
            Teacher.objects.get(email=request.user.email)
            return True
        except Teacher.DoesNotExist:
            pass
        
        # Students can only access their own data
        try:
            student = Student.objects.get(email=request.user.email)
            return obj.student == student
        except Student.DoesNotExist:
            return False
```

---

## 6. Frontend Integration

### **How Frontend Uses the Authentication System**

#### **A. OAuth Login Flow:**
```javascript
// React example
const handleGoogleLogin = () => {
  // Redirect to your OAuth endpoint
  window.location.href = 'http://localhost:8000/api/auth/google/';
};

// Handle the callback (you'll need to set up a route for this)
const handleOAuthCallback = async (code) => {
  try {
    const response = await fetch(`http://localhost:8000/api/auth/google/callback/?code=${code}`);
    const data = await response.json();
    
    // Store tokens
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    
    // Redirect to dashboard
    navigate('/dashboard');
  } catch (error) {
    console.error('OAuth error:', error);
  }
};
```

#### **B. Making Authenticated API Calls:**
```javascript
// API utility function
const apiCall = async (endpoint, options = {}) => {
  const token = localStorage.getItem('access_token');
  
  const response = await fetch(`http://localhost:8000/api/${endpoint}`, {
    ...options,
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });
  
  if (response.status === 401) {
    // Token expired, try to refresh
    await refreshToken();
    // Retry the request
    return apiCall(endpoint, options);
  }
  
  return response.json();
};

// Refresh token function
const refreshToken = async () => {
  const refresh_token = localStorage.getItem('refresh_token');
  
  try {
    const response = await fetch('http://localhost:8000/api/auth/token/refresh/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh: refresh_token }),
    });
    
    const data = await response.json();
    localStorage.setItem('access_token', data.access);
  } catch (error) {
    // Refresh failed, redirect to login
    localStorage.clear();
    window.location.href = '/login';
  }
};
```

#### **C. Protected Routes:**
```javascript
// React Router protected route
const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem('access_token');
  
  if (!token) {
    return <Navigate to="/login" />;
  }
  
  return children;
};

// Usage
<Route 
  path="/dashboard" 
  element={
    <ProtectedRoute>
      <Dashboard />
    </ProtectedRoute>
  } 
/>
```

#### **D. Role-Based UI:**
```javascript
// Check user role for UI rendering
const UserDashboard = () => {
  const user = JSON.parse(localStorage.getItem('user'));
  
  if (user.teacher_id) {
    return <TeacherDashboard />;
  } else {
    return <StudentDashboard />;
  }
};
```

---

## 7. Troubleshooting Common Errors

### **Error: "No module named 'requests'"`
```bash
# Solution: Install missing package
pip install requests
pip freeze > requirements.txt
```

### **Error: "No module named 'cryptography'"`
```bash
# Solution: Install missing package
pip install cryptography
pip freeze > requirements.txt
```

### **Error: "allauth.account.middleware.AccountMiddleware must be added to settings.MIDDLEWARE"**
```python
# Solution: Add to MIDDLEWARE in settings.py
MIDDLEWARE = [
    # ... existing middleware ...
    'allauth.account.middleware.AccountMiddleware',
]
```

### **Error: "Application labels aren't unique, duplicates: auth"**
```bash
# Solution: Rename your auth app
mv auth custom_auth
# Update INSTALLED_APPS in settings.py
# Update app name in custom_auth/apps.py
```

### **Error: "'GoogleProvider' object has no attribute 'get_app'"**
```python
# Solution: Use direct Google API calls instead of Allauth's internal methods
# (This is what we implemented in the guide)
```

### **Error: "Google OAuth app not configured"**
```bash
# Solution: Set up Social Application in Django Admin
# Go to /admin/ → Social Applications → Add Social Application
# Provider: Google
# Client ID: Your Google Client ID
# Secret Key: Your Google Client Secret
```

### **Error: "No authorization code provided"**
```python
# Solution: Check that your callback URL is correct
# Should be: http://localhost:8000/api/auth/google/callback/
# Make sure it matches in Google Cloud Console
```

### **Error: "Failed to exchange code for token"**
```python
# Solution: Check your Google OAuth credentials
# Verify Client ID and Secret are correct
# Check redirect URI matches exactly
```

### **Error: "JWT token invalid"**
```python
# Solution: Check token format in Authorization header
# Should be: Authorization: Bearer <token>
# Make sure token hasn't expired
```

---

## 8. Suggested Commit Points

### **Initial Setup:**
```bash
git add .
git commit -m "Initial Django project setup with billing models"
```

### **After Installing Auth Packages:**
```bash
git add requirements.txt
git commit -m "Add authentication packages: django-allauth, djangorestframework-simplejwt"
```

### **After Updating Settings:**
```bash
git add maple_key_backend/settings.py
git commit -m "Configure OAuth and JWT authentication settings"
```

### **After Creating Auth Views:**
```bash
git add custom_auth/
git commit -m "Implement Google OAuth callback and JWT token generation"
```

### **After Setting Up URLs:**
```bash
git add maple_key_backend/urls.py custom_auth/urls.py
git commit -m "Add authentication URL patterns"
```

### **After Admin Configuration:**
```bash
git add .
git commit -m "Configure Google OAuth in Django admin"
```

### **After Testing OAuth Flow:**
```bash
git add .
git commit -m "OAuth flow working - users can authenticate with Google and receive JWT tokens"
```

### **After Adding Permissions:**
```bash
git add billing/permissions.py billing/views.py
git commit -m "Add role-based permissions for teachers and students"
```

### **After Frontend Integration:**
```bash
git add .
git commit -m "Complete authentication system with frontend integration examples"
```

---

## Additional OAuth Providers

### **Facebook OAuth:**
```python
# Add to INSTALLED_APPS
'allauth.socialaccount.providers.facebook',

# Add to SOCIALACCOUNT_PROVIDERS
'facebook': {
    'APP': {
        'client_id': config('FACEBOOK_CLIENT_ID'),
        'secret': config('FACEBOOK_CLIENT_SECRET'),
    },
    'SCOPE': ['email', 'public_profile'],
}
```

### **GitHub OAuth:**
```python
# Add to INSTALLED_APPS
'allauth.socialaccount.providers.github',

# Add to SOCIALACCOUNT_PROVIDERS
'github': {
    'APP': {
        'client_id': config('GITHUB_CLIENT_ID'),
        'secret': config('GITHUB_CLIENT_SECRET'),
    },
    'SCOPE': ['user:email'],
}
```

### **LinkedIn OAuth:**
```python
# Add to INSTALLED_APPS
'allauth.socialaccount.providers.linkedin',

# Add to SOCIALACCOUNT_PROVIDERS
'linkedin': {
    'APP': {
        'client_id': config('LINKEDIN_CLIENT_ID'),
        'secret': config('LINKEDIN_CLIENT_SECRET'),
    },
    'SCOPE': ['r_emailaddress', 'r_liteprofile'],
}
```

---

## Summary

This guide covers:
- ✅ **Google OAuth setup** with JWT tokens
- ✅ **Traditional Django authentication** for admin
- ✅ **Role-based permissions** for teachers and students
- ✅ **Frontend integration** examples
- ✅ **Troubleshooting** common errors
- ✅ **Suggested commit points** for version control

**Key Takeaways:**
1. **Use both OAuth and traditional auth** - they serve different purposes
2. **JWT tokens** are perfect for API authentication
3. **Role-based permissions** protect your data
4. **Test incrementally** - commit after each working step
5. **Frontend integration** requires token management

**Next Steps:**
1. Implement the remaining auth endpoints (refresh, logout, profile)
2. Add more OAuth providers if needed
3. Implement password reset functionality
4. Add email verification
5. Set up production configurations

---

*This guide serves as your complete reference for Django authentication. Bookmark it for future projects!*
