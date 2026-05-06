"""
Signals for the billing app
Handles cascading deletion between User, ApprovedEmail, and UserRegistrationRequest models
"""
import logging

from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver
from .models import User, ApprovedEmail, UserRegistrationRequest

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=User)
def delete_approved_email_on_user_delete(sender, instance, **kwargs):
    """
    When a User is deleted, remove their ApprovedEmail and UserRegistrationRequest entries
    """
    logger.info('[SIGNAL] User deleted: %s - cleaning up related records', instance.email)

    # Delete ApprovedEmail
    try:
        approved_email = ApprovedEmail.objects.get(email=instance.email)
        approved_email.delete()
        logger.info('[SIGNAL] Deleted ApprovedEmail for %s', instance.email)
    except ApprovedEmail.DoesNotExist:
        logger.debug('[SIGNAL] No ApprovedEmail found for %s (OK)', instance.email)

    # Delete UserRegistrationRequests
    reg_requests = UserRegistrationRequest.objects.filter(email=instance.email)
    if reg_requests.exists():
        count = reg_requests.count()
        reg_requests.delete()
        logger.info('[SIGNAL] Deleted %s UserRegistrationRequest(s) for %s', count, instance.email)
    else:
        logger.debug('[SIGNAL] No UserRegistrationRequest found for %s (OK)', instance.email)


@receiver(pre_delete, sender=ApprovedEmail)
def delete_user_on_approved_email_delete(sender, instance, **kwargs):
    """
    When an ApprovedEmail is deleted, delete the corresponding User and UserRegistrationRequests
    Note: Using pre_delete to avoid circular deletion issues
    """
    logger.info('[SIGNAL] ApprovedEmail being deleted: %s - cleaning up related records', instance.email)

    # Delete User
    try:
        user = User.objects.get(email=instance.email)
        # Temporarily disconnect the signal to avoid infinite loop
        post_delete.disconnect(delete_approved_email_on_user_delete, sender=User)
        user.delete()
        # Reconnect the signal
        post_delete.connect(delete_approved_email_on_user_delete, sender=User)
        logger.info('[SIGNAL] Deleted User for %s', instance.email)
    except User.DoesNotExist:
        logger.debug('[SIGNAL] No User found for %s (OK)', instance.email)

    # Delete UserRegistrationRequests
    reg_requests = UserRegistrationRequest.objects.filter(email=instance.email)
    if reg_requests.exists():
        count = reg_requests.count()
        reg_requests.delete()
        logger.info('[SIGNAL] Deleted %s UserRegistrationRequest(s) for %s', count, instance.email)
    else:
        logger.debug('[SIGNAL] No UserRegistrationRequest found for %s (OK)', instance.email)
