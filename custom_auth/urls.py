from django.urls import path
from . import views

urlpatterns = [
    # OAuth endpoints
    path('google/', views.google_oauth, name='google_oauth'),
    path('google/callback/', views.google_oauth_callback, name='google_callback'),
    
    # JWT endpoints
    path('token/', views.get_jwt_token, name='get_jwt_token'),
    path('token/refresh/', views.refresh_jwt_token, name='refresh_jwt_token'),
    
    # User profile endpoints
    path('user/', views.user_profile, name='user_profile'),
    path('logout/', views.logout, name='logout'),
]
