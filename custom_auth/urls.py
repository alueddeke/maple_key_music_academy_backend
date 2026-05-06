from django.urls import path
from . import views

urlpatterns = [
    # PKCE OAuth endpoints
    path('google/exchange/', views.google_exchange, name='google_exchange'),

    # Registration endpoints
    path('register/', views.register_with_email, name='register_with_email'),

    # JWT endpoints
    path('token/', views.get_jwt_token, name='get_jwt_token'),
    path('token/refresh/', views.refresh_jwt_token, name='refresh_jwt_token'),

    # User profile endpoints
    path('user/', views.user_profile, name='user_profile'),
    path('logout/', views.logout, name='logout'),

    # Password reset endpoints
    path('password-reset/', views.password_reset_request, name='password_reset_request'),
    path('password-reset/validate/', views.password_reset_validate_token, name='password_reset_validate'),
    path('password-reset/confirm/', views.password_reset_confirm, name='password_reset_confirm'),
]
