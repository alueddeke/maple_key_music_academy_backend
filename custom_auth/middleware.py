"""
Email Whitelist Middleware

This middleware checks if authenticated users' emails are in the ALLOWED_EMAILS list.
If a user's email is not whitelisted, they are denied access (even if previously authenticated).
This prevents existing users with non-whitelisted emails from accessing the system.
"""
from django.conf import settings
from django.http import JsonResponse
from rest_framework import status


class EmailWhitelistMiddleware:
    """
    Middleware to check if authenticated users' emails are whitelisted.

    This middleware runs on every request and checks if:
    1. User is authenticated
    2. ALLOWED_EMAILS is configured
    3. User's email is in the whitelist

    If conditions are met but email is not whitelisted, returns 403 Forbidden.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if user is authenticated
        if request.user.is_authenticated:
            # Check if ALLOWED_EMAILS is configured
            if hasattr(settings, 'ALLOWED_EMAILS') and settings.ALLOWED_EMAILS:
                user_email = request.user.email.lower() if request.user.email else ''

                # Check if user's email is in the whitelist
                if user_email not in settings.ALLOWED_EMAILS:
                    # User is authenticated but email not whitelisted - deny access
                    return JsonResponse({
                        'error': 'Your email is not authorized. Please contact support.',
                        'detail': 'Email whitelist restriction'
                    }, status=status.HTTP_403_FORBIDDEN)

        # Continue with request if email is whitelisted or user not authenticated
        response = self.get_response(request)
        return response
