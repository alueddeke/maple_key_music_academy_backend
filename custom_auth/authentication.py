"""
JWT authentication with password-change / deactivation revocation (MAP-141).

simplejwt access tokens are stateless: a 60-minute token issued before a
password reset (or before management deactivated the account) would keep
working until it expired. This subclass rejects any access token whose
`iat` is older than User.password_changed_at; revoke_user_tokens() stamps
that field and blacklists every outstanding refresh token for the user, so
both halves of a session die together.

Whole-second comparison (D5, 2026-09-10): simplejwt 5.5.1 writes
`iat = timegm(utctimetuple())` — truncated to the second — while
password_changed_at carries microseconds. Flooring both sides keeps a token
issued in the same second *after* the reset valid.
"""
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication as BaseJWTAuthentication
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken


class JWTAuthentication(BaseJWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        changed_at = getattr(user, 'password_changed_at', None)
        if changed_at is not None:
            issued_at = validated_token.get('iat')
            if issued_at is None or int(issued_at) < int(changed_at.timestamp()):
                raise AuthenticationFailed(
                    'Token issued before the last password change', code='password_changed'
                )
        return user


def revoke_user_tokens(user):
    """
    Stamp password_changed_at = now and blacklist every outstanding refresh
    token for `user`. Called after a password reset and after management
    deactivation (MAP-141).
    """
    user.password_changed_at = timezone.now()
    user.save(update_fields=['password_changed_at'])
    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)
