"""
Signals for the billing app
Handles cascading deletion between User, ApprovedEmail, and UserRegistrationRequest models
"""
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver
from .models import User, ApprovedEmail, UserRegistrationRequest


@receiver(post_delete, sender=User)
def delete_approved_email_on_user_delete(sender, instance, **kwargs):
    """
    When a User is deleted, remove their ApprovedEmail and UserRegistrationRequest entries
    """
    print(f"[SIGNAL] User deleted: {instance.email} - cleaning up related records...")

    # Delete ApprovedEmail
    try:
        approved_email = ApprovedEmail.objects.get(email=instance.email)
        approved_email.delete()
        print(f"[SIGNAL] ✓ Deleted ApprovedEmail for {instance.email}")
    except ApprovedEmail.DoesNotExist:
        print(f"[SIGNAL] No ApprovedEmail found for {instance.email} (OK)")

    # Delete UserRegistrationRequests
    reg_requests = UserRegistrationRequest.objects.filter(email=instance.email)
    if reg_requests.exists():
        count = reg_requests.count()
        reg_requests.delete()
        print(f"[SIGNAL] ✓ Deleted {count} UserRegistrationRequest(s) for {instance.email}")
    else:
        print(f"[SIGNAL] No UserRegistrationRequest found for {instance.email} (OK)")


@receiver(pre_delete, sender=ApprovedEmail)
def delete_user_on_approved_email_delete(sender, instance, **kwargs):
    """
    When an ApprovedEmail is deleted, delete the corresponding User and UserRegistrationRequests
    Note: Using pre_delete to avoid circular deletion issues
    """
    print(f"[SIGNAL] ApprovedEmail being deleted: {instance.email} - cleaning up related records...")

    # Delete User
    try:
        user = User.objects.get(email=instance.email)
        # Temporarily disconnect the signal to avoid infinite loop
        post_delete.disconnect(delete_approved_email_on_user_delete, sender=User)
        user.delete()
        # Reconnect the signal
        post_delete.connect(delete_approved_email_on_user_delete, sender=User)
        print(f"[SIGNAL] ✓ Deleted User for {instance.email}")
    except User.DoesNotExist:
        print(f"[SIGNAL] No User found for {instance.email} (OK)")

    # Delete UserRegistrationRequests
    reg_requests = UserRegistrationRequest.objects.filter(email=instance.email)
    if reg_requests.exists():
        count = reg_requests.count()
        reg_requests.delete()
        print(f"[SIGNAL] ✓ Deleted {count} UserRegistrationRequest(s) for {instance.email}")
    else:
        print(f"[SIGNAL] No UserRegistrationRequest found for {instance.email} (OK)")
