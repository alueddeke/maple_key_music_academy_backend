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
