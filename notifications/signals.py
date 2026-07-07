"""Signal receivers that fire notifications on billing state changes.

Receivers live HERE (not in billing) so the notification subsystem stays
fully decoupled: billing's approval/rejection code paths are untouched —
we only observe saves. Connected from NotificationsConfig.ready().
"""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from billing.models import Invoice, MonthlyInvoiceBatch

from .services import notify_batch_rejected, notify_invoice_rejected

logger = logging.getLogger(__name__)

# Stash of pre-save status per instance pk, so post_save can detect transitions.
_batch_old_status = {}
_invoice_old_status = {}


@receiver(pre_save, sender=MonthlyInvoiceBatch, dispatch_uid='notifications_batch_pre_save')
def _capture_batch_status(sender, instance, **kwargs):
    if instance.pk:
        old = sender.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
        _batch_old_status[instance.pk] = old


@receiver(post_save, sender=MonthlyInvoiceBatch, dispatch_uid='notifications_batch_post_save')
def _on_batch_saved(sender, instance, created, **kwargs):
    if created:
        return
    old_status = _batch_old_status.pop(instance.pk, None)
    # Rejection flow sets the batch back to 'draft' with a rejection_reason
    # (billing/views/management.py management_reject_batch) — that transition
    # is the "invoice rejected" event.
    is_rejection = (
        old_status == 'submitted'
        and instance.status == 'draft'
        and bool((instance.rejection_reason or '').strip())
    )
    if not is_rejection:
        return
    try:
        notify_batch_rejected(instance)
    except Exception:
        logger.exception(
            "Failed to create rejection notification for batch %s", instance.pk
        )


@receiver(pre_save, sender=Invoice, dispatch_uid='notifications_invoice_pre_save')
def _capture_invoice_status(sender, instance, **kwargs):
    if instance.pk:
        old = sender.objects.filter(pk=instance.pk).values_list('status', flat=True).first()
        _invoice_old_status[instance.pk] = old


@receiver(post_save, sender=Invoice, dispatch_uid='notifications_invoice_post_save')
def _on_invoice_saved(sender, instance, created, **kwargs):
    if created:
        return
    old_status = _invoice_old_status.pop(instance.pk, None)
    is_rejection = (
        old_status != 'rejected'
        and instance.status == 'rejected'
        and instance.teacher_id is not None
    )
    if not is_rejection:
        return
    try:
        notify_invoice_rejected(instance)
    except Exception:
        logger.exception(
            "Failed to create rejection notification for invoice %s", instance.pk
        )
