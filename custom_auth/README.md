# Custom Auth App

The Custom Auth app handles authentication, authorization, and user session management for the Maple Key Music Academy backend.

## 🏗️ Architecture Overview

This app provides **mixed authentication** supporting both:
- **OAuth Authentication** - Google OAuth for easy teacher registration
- **JWT Token Authentication** - Email/password login with JWT tokens
- **Role-Based Authorization** - Decorators for different user permission levels

## 🔐 Authentication Methods

### 1. Google OAuth Flow
```
1. User clicks "Login with Google"
2. Redirects to Google OAuth
3. Google returns authorization code
4. Backend exchanges code for user info
5. Creates/finds user in database
6. Returns JWT tokens
```

**Endpoints:**
- `GET /api/auth/google/` - Initiate Google OAuth
- `GET /api/auth/google/callback/` - Handle OAuth callback

### 2. JWT Token Authentication
```
1. User provides email/password
2. Backend validates credentials
3. Returns access_token and refresh_token
4. Frontend uses access_token for API calls
5. Refresh token when access_token expires
```

**Endpoints:**
- `POST /api/auth/token/` - Get JWT tokens (email/password)
- `POST /api/auth/token/refresh/` - Refresh access token
- `POST /api/auth/logout/` - Blacklist refresh token

## 🛡️ Authorization System

### Permission Decorators

#### `@role_required(*allowed_roles)`
```python
@role_required('teacher', 'management')
def some_endpoint(request):
    # Only teachers and management can access
```

#### `@teacher_required`
```python
@teacher_required
def teacher_only_endpoint(request):
    # Only teachers can access
```

#### `@management_required`
```python
@management_required
def management_only_endpoint(request):
    # Only management can access
```

#### `@teacher_or_management_required`
```python
@teacher_or_management_required
def teacher_or_management_endpoint(request):
    # Teachers or management can access
```

#### `@owns_resource_or_management(resource_field)`
```python
@owns_resource_or_management('teacher')
def teacher_resource_endpoint(request):
    # Teachers can access their own resources, management can access all
```

### Permission Logic

**Authentication Check:**
- Verifies JWT token is valid
- Ensures user is authenticated

**Role Check:**
- Verifies user has one of the required roles
- Returns 403 if role doesn't match

**Approval Check:**
- Management users are auto-approved
- Teachers/Students must be approved by management
- Returns 403 if account is pending approval

**Resource Ownership:**
- Teachers can only access their own resources
- Students can only access their own resources
- Management can access all resources

## 🔑 JWT Token System

### Token Configuration
```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),  # 1 hour
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),     # 1 day
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
}
```

### Token Usage
```javascript
// Include in API requests
headers: {
    'Authorization': 'Bearer <access_token>',
    'Content-Type': 'application/json'
}
```

### Token Refresh Flow
```javascript
// When access token expires
POST /api/auth/token/refresh/
{
    "refresh": "<refresh_token>"
}

// Response
{
    "access_token": "<new_access_token>",
    "refresh_token": "<refresh_token>"
}
```

## 👤 User Profile Management

### Get Current User Profile
```python
GET /api/auth/user/
Authorization: Bearer <access_token>
```

**Response:**
```json
{
    "user": {
        "email": "teacher@example.com",
        "name": "John Teacher",
        "user_id": 123,
        "user_type": "teacher",
        "is_approved": true,
        "first_name": "John",
        "last_name": "Teacher",
        "phone_number": "555-1234",
        "address": "123 Music St",
        "bio": "Piano teacher with 10 years experience",
        "instruments": "Piano, Guitar",
        "hourly_rate": 65.00
    }
}
```

## 🔄 OAuth Integration

### Google OAuth Setup
1. **Google Cloud Console**: Create OAuth 2.0 credentials
2. **Django Admin**: Configure Social App with client ID/secret
3. **Environment Variables**: Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`

### OAuth User Creation
```python
# When user completes OAuth
user, created = User.objects.get_or_create(
    email=user_data.get('email'),
    defaults={
        'username': user_data.get('email'),
        'first_name': user_data.get('given_name', ''),
        'last_name': user_data.get('family_name', ''),
        'user_type': 'teacher',  # Default to teacher for OAuth
        'oauth_provider': 'google',
        'oauth_id': user_data.get('id'),
        'is_approved': False,  # Requires management approval
    }
)
```

## 🚫 Logout System

### Token Blacklisting
```python
POST /api/auth/logout/
{
    "refresh": "<refresh_token>"
}
```

**What happens:**
- Refresh token is blacklisted
- User must re-authenticate to get new tokens
- Access token remains valid until expiration

## 🔧 Configuration

### Settings Requirements
```python
# Required in settings.py
AUTH_USER_MODEL = 'billing.User'
INSTALLED_APPS = [
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'custom_auth',
]
```

### Environment Variables
```bash
# Required for OAuth
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret

# Required for Django
SECRET_KEY=your_django_secret_key
DEBUG=True
```

## 🧪 Testing Authentication

### Test JWT Authentication
```python
# Login
response = requests.post('/api/auth/token/', json={
    'email': 'teacher@example.com',
    'password': 'password123'
})

# Use token
headers = {'Authorization': f'Bearer {response.json()["access_token"]}'}
response = requests.get('/api/billing/lessons/', headers=headers)
```

### Test OAuth Flow
```python
# Initiate OAuth
response = requests.get('/api/auth/google/')

# Handle callback (simplified)
response = requests.get('/api/auth/google/callback/?code=oauth_code')
```

## 🛠️ Error Handling

### Common Error Responses

**401 Unauthorized:**
```json
{
    "error": "Authentication required",
    "message": "Please provide a valid JWT token"
}
```

**403 Forbidden (Wrong Role):**
```json
{
    "error": "Insufficient permissions",
    "message": "This endpoint requires one of: teacher, management"
}
```

**403 Forbidden (Pending Approval):**
```json
{
    "error": "Account pending approval",
    "message": "Your account is awaiting management approval"
}
```

**403 Forbidden (Resource Access):**
```json
{
    "error": "Access denied",
    "message": "You can only access your own resources"
}
```

## 🔒 Security Features

### Token Security
- **Short-lived access tokens** (1 hour)
- **Refresh token rotation** (optional)
- **Token blacklisting** on logout
- **HTTPS required** in production

### Permission Security
- **Role-based access control**
- **Resource ownership validation**
- **Approval status checking**
- **Audit trail** for all actions

### OAuth Security
- **State parameter validation** (recommended)
- **Secure token exchange**
- **User data validation**
- **Account linking** for existing users

## 🚀 Frontend Integration

### Login Component
```javascript
const login = async (email, password) => {
    const response = await fetch('/api/auth/token/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
    });
    
    const data = await response.json();
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
};
```

### API Client with Auto-Refresh
```javascript
const apiClient = axios.create({
    baseURL: '/api',
    headers: { 'Content-Type': 'application/json' }
});

// Add token to requests
apiClient.interceptors.request.use((config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Handle token refresh
apiClient.interceptors.response.use(
    (response) => response,
    async (error) => {
        if (error.response?.status === 401) {
            await refreshToken();
            return apiClient.request(error.config);
        }
        return Promise.reject(error);
    }
);
```

## 📝 Usage Examples

### Teacher Login Flow
```javascript
// 1. Login
const loginResponse = await fetch('/api/auth/token/', {
    method: 'POST',
    body: JSON.stringify({
        email: 'teacher@example.com',
        password: 'password123'
    })
});

// 2. Store tokens
const { access_token, refresh_token, user } = await loginResponse.json();
localStorage.setItem('access_token', access_token);

// 3. Check approval status
if (!user.is_approved) {
    showMessage('Your account is pending management approval');
}

// 4. Redirect based on role
if (user.user_type === 'teacher') {
    router.push('/teacher/dashboard');
}
```

### Google OAuth Flow
```javascript
// 1. Redirect to Google OAuth
window.location.href = '/api/auth/google/';

// 2. Handle callback (automatic redirect)
// 3. User is logged in with JWT tokens
```

## 🔮 Future Enhancements

- **Multi-factor authentication**
- **Social login providers** (Facebook, Apple)
- **Password reset flow**
- **Account verification emails**
- **Session management dashboard**
- **Advanced permission system**
- **API rate limiting**
- **Audit logging**
