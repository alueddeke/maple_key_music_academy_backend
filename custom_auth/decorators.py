"""
Custom authentication decorators for the music academy backend.

This module provides decorators to protect API endpoints with JWT authentication
and implement role-based access control using the unified User model.
"""

from functools import wraps
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()

#wrappers/middleware

def role_required(*allowed_roles):
    """
    Decorator that requires user to have one of the specified roles.
    Also checks approval status for non-management users.
    
    Usage: @role_required('teacher', 'management')
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return Response({
                    'error': 'Authentication required',
                    'message': 'Please provide a valid JWT token'
                }, status=status.HTTP_401_UNAUTHORIZED)
            
            # Check role
            if request.user.user_type not in allowed_roles:
                return Response({
                    'error': 'Insufficient permissions',
                    'message': f'This endpoint requires one of: {", ".join(allowed_roles)}'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check approval status (management is auto-approved)
            if request.user.user_type != 'management' and not request.user.is_approved:
                return Response({
                    'error': 'Account pending approval',
                    'message': 'Your account is awaiting management approval'
                }, status=status.HTTP_403_FORBIDDEN)

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def teacher_required(view_func):
    """Shorthand decorator for teacher-only endpoints"""
    return role_required('teacher')(view_func)

def management_required(view_func):
    """Shorthand decorator for management-only endpoints"""
    return role_required('management')(view_func)

def teacher_or_management_required(view_func):
    """Shorthand decorator for teacher or management endpoints"""
    return role_required('teacher', 'management')(view_func)

def owns_resource_or_management(resource_field='teacher'):
    """
    Decorator that ensures users can only access their own resources,
    unless they are management (who can access everything).
    
    Usage: @owns_resource_or_management('teacher') for teacher-owned resources
           @owns_resource_or_management('student') for student-owned resources
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # First apply role checking
            role_check = role_required('teacher', 'student', 'management')(view_func)
            response = role_check(request, *args, **kwargs)
            if hasattr(response, 'status_code') and response.status_code != 200:
                return response
            
            # Management can access everything
            if request.user.user_type == 'management':
                return view_func(request, *args, **kwargs)
            
            # For non-management users, add resource ownership to request
            if resource_field == 'teacher' and request.user.user_type == 'teacher':
                request.resource_owner = request.user
            elif resource_field == 'student' and request.user.user_type == 'student':
                request.resource_owner = request.user
            else:
                return Response({
                    'error': 'Access denied',
                    'message': 'You can only access your own resources'
                }, status=status.HTTP_403_FORBIDDEN)
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

# Legacy decorators for backward compatibility (deprecated)
def jwt_required(view_func):
    """
    Legacy decorator - use role_required instead.
    This decorator ensures that only authenticated users with valid JWT tokens
    can access the protected endpoint.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return Response({
                'error': 'Authentication required',
                'message': 'Please provide a valid JWT token in the Authorization header'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper

def teacher_owns_resource(view_func):
    """
    Legacy decorator - use owns_resource_or_management instead.
    This decorator ensures teachers can only access their own resources.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return Response({
                'error': 'Authentication required',
                'message': 'Please provide a valid JWT token in the Authorization header'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Check if user is a teacher
        if request.user.user_type != 'teacher':
            return Response({
                'error': 'Teacher account required',
                'message': 'This endpoint requires a teacher account'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Check approval status
        if not request.user.is_approved:
            return Response({
                'error': 'Account pending approval',
                'message': 'Your account is awaiting management approval'
            }, status=status.HTTP_403_FORBIDDEN)

        # Check if the teacher_id in the URL matches the authenticated teacher
        teacher_id = kwargs.get('teacher_id') or kwargs.get('pk')
        if teacher_id and int(teacher_id) != request.user.id:
            return Response({
                'error': 'Access denied',
                'message': 'You can only access your own resources'
            }, status=status.HTTP_403_FORBIDDEN)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper