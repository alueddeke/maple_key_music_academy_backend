"""
MAP-177: platform superuser/staff is held only by settings.PLATFORM_ADMIN_EMAILS.

Data-only. forward()/reverse() are module-level so tests can import and call
them (pytest runs --no-migrations). Uses .update() on purpose: it bypasses
User.save() and simple_history; the pre-deploy DB backup is the recovery point.
"""
import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import migrations
from django.db.models import Q

logger = logging.getLogger(__name__)


def forward(apps, schema_editor):
    User = apps.get_model('billing', 'User')
    allowlist = list(settings.PLATFORM_ADMIN_EMAILS)
    if not allowlist:
        raise ImproperlyConfigured(
            'PLATFORM_ADMIN_EMAILS is empty; 0070_demote_non_platform_admins refuses to run '
            'without a platform admin allowlist.'
        )

    if not User.objects.exists():
        logger.info('0070_demote_non_platform_admins: fresh database, nothing to demote')
        return

    present = set(User.objects.filter(email__in=allowlist).values_list('email', flat=True))
    missing = [email for email in allowlist if email not in present]
    if missing:
        raise ImproperlyConfigured(
            'PLATFORM_ADMIN_EMAILS names accounts with no User row: ' + ', '.join(missing)
        )

    demoted = list(
        User.objects.exclude(email__in=allowlist)
        .filter(Q(is_staff=True) | Q(is_superuser=True))
        .values_list('email', flat=True)
    )
    count = User.objects.exclude(email__in=allowlist).update(is_staff=False, is_superuser=False)
    logger.info(
        '0070_demote_non_platform_admins: cleared is_staff/is_superuser on %d rows; '
        'demoted %d account(s): %s', count, len(demoted), ', '.join(demoted) or '-'
    )


def reverse(apps, schema_editor):
    # Restore the pre-0070 derivation exactly (User.save() set both flags for management).
    User = apps.get_model('billing', 'User')
    User.objects.filter(user_type='management').update(is_staff=True, is_superuser=True)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0069_invoicesenditem_claimed_at'),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
