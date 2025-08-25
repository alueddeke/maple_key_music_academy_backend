from django.shortcuts import redirect, render
from allauth.socialaccount.providers.google.views import oauth2_login, GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from allauth.socialaccount.providers.oauth2.views import OAuth2LoginView
from allauth.socialaccount.models import SocialLogin
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
    """redirect to google for oauth flow"""
    return oauth2_login(request, 'google')



@api_view(['GET'])
def google_oauth_callback(request):
    """Google OAuth callback endpoint"""
    try:
        # Step 1: Get the authorization code from the request
        code = request.GET.get('code')
        if not code:
            return Response({'error': 'No authorization code provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Step 2: Get Google OAuth app configuration
        from allauth.socialaccount.models import SocialApp
        try:
            app = SocialApp.objects.get(provider='google')
        except SocialApp.DoesNotExist:
            return Response({'error': 'Google OAuth app not configured. Please set up in Django admin.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Step 3: Exchange code for tokens using Google API directly
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
        
        # Step 5: Get or create Django user
        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=user_data.get('email'),
            defaults={
                'username': user_data.get('email'),
                'first_name': user_data.get('given_name', ''),
                'last_name': user_data.get('family_name', ''),
            }
        )
        
        # Step 6: Get or create Teacher
        teacher, teacher_created = Teacher.objects.get_or_create(
            email=user.email,
            defaults={
                'name': f"{user.first_name} {user.last_name}".strip() or user.email,
                'address': '',  # Will be filled later
                'phoneNumber': '',  # Will be filled later
            }
        )
        
        # Step 7: Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        # Get user name from Google data or use email as fallback
        user_name = f"{user.first_name} {user.last_name}".strip()
        if not user_name:
            user_name = user_data.get('name', user.email)  # Use Google's name or email
        
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

 

@api_view(['POST'])
def get_jwt_token(request):
    """Get JWT token endpoint"""
    return Response({'message': 'JWT token endpoint - to be implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)

@api_view(['POST'])
def refresh_jwt_token(request):
    """Refresh JWT token endpoint"""
    return Response({'message': 'JWT refresh endpoint - to be implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)

@api_view(['GET'])
def user_profile(request):
    """Get user profile endpoint"""
    return Response({'message': 'User profile endpoint - to be implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)

@api_view(['POST'])
def logout(request):
    """Logout endpoint"""
    return Response({'message': 'Logout endpoint - to be implemented'}, status=status.HTTP_501_NOT_IMPLEMENTED)
