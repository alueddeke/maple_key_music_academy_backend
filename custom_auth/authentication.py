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


# MAP-220: a soft-deleted user must not keep its unique address hostage.
REMOVED_EMAIL_DOMAIN = 'removed.maplekeymusic.internal'
_EMAIL_MAX_LENGTH = 254


def release_email(user):
    """
    Rewrite a removed user's email to
    ``removed+{id}+{original_local}@removed.maplekeymusic.internal`` so the
    original address can be reused, while staying readable in the new value
    and in HistoricalUser. Idempotent; does not save.
    """
    if user.email.lower().endswith('@' + REMOVED_EMAIL_DOMAIN):
        return user.email
    original_local = user.email.split('@', 1)[0]
    suffix = '@' + REMOVED_EMAIL_DOMAIN
    local = f'removed+{user.id}+{original_local}'[: _EMAIL_MAX_LENGTH - len(suffix)]
    user.email = local + suffix
    return user.email


def removed_account_message(email, exclude_pk=None):
    """
    If `email` is held by an INACTIVE user (a row removed before MAP-220
    released addresses), return the validation message naming it; else None.
    """
    from django.contrib.auth import get_user_model
    qs = get_user_model().objects.filter(email__iexact=email, is_active=False)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    holder = qs.only('id').first()
    if holder is None:
        return None
    return f'This email belongs to a removed account (id {holder.id})'
