"""
billing/services/webhook_processing.py — Helcim webhook credit reconciliation.

Shared by:
  - billing/views/webhooks.py     (live webhook receipt + Helcim retry re-processing)
  - retry_webhook_events command  (manual/scheduled recovery of stuck events)
  - HelcimWebhookEvent admin action

Money-safety rules enforced here:
  - Credit is applied ONLY for transactions with status=APPROVED and
    type=purchase/capture. Declined attempts and refunds/reversals must
    never increase a student's wallet.
  - The invoice is marked paid only when the approved amount covers
    invoice.amount; a short payment still credits the wallet (the money is
    real) but leaves the invoice open and flags the event credited_partial.
  - Re-running is safe: terminal states are never re-processed, and the
    'credited*' write happens in the same atomic block that stamps the state.
  - Helcim HTTP calls stay OUTSIDE transaction.atomic() (STATE.md hard rule).
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import (
    HelcimWebhookEvent,
    PreBillingInvoice,
    StudentCreditAccount,
    CreditTransaction,
)
from .helcim_client import HelcimClient, HelcimAPIError

logger = logging.getLogger(__name__)

# States that a retry (Helcim redelivery, management command, admin action)
# is allowed to re-process. Everything else is terminal.
RETRYABLE_STATES = {'pending', 'enrichment_failed', 'no_invoice', 'no_account'}

CREDITABLE_TYPES = {'purchase', 'capture'}


def process_webhook_event(event):
    """
    Enrich a HelcimWebhookEvent from the card-transactions API and apply
    student credit when the transaction qualifies.

    Returns the event with processing_status set to a terminal or retryable
    state. Never raises for Helcim/API problems — failures land in
    processing_status + last_error for admin visibility.
    """
    if event.processing_status not in RETRYABLE_STATES:
        return event

    # Enrichment — outside any DB transaction. Re-fetch when either the
    # invoice number or the gating fields are missing (legacy rows predate
    # transaction_status).
    if not event.invoice_id or not event.transaction_status:
        client = HelcimClient(school=event.school)
        try:
            tx = client.get_card_transaction(event.helcim_transaction_id)
        except HelcimAPIError as e:
            event.processing_status = 'enrichment_failed'
            event.last_error = str(e)
            event.processed_at = timezone.now()
            event.save(update_fields=['processing_status', 'last_error', 'processed_at'])
            return event
        event.invoice_id = str(tx.get('invoiceNumber', ''))
        # T-18-C7: Decimal(str(...)) — never float() for money (CONVENTIONS.md)
        event.amount = Decimal(str(tx.get('amount', '0')))
        event.transaction_status = str(tx.get('status', ''))
        event.transaction_type = str(tx.get('type', ''))
        event.save(update_fields=['invoice_id', 'amount', 'transaction_status', 'transaction_type'])

    # Gating — strict: anything not an approved purchase/capture never credits.
    tx_status = event.transaction_status.upper()
    tx_type = event.transaction_type.lower()
    if tx_status != 'APPROVED':
        return _finalize(event, 'not_approved', f'transaction status={event.transaction_status or "(missing)"}')
    if tx_type not in CREDITABLE_TYPES:
        # Refunds/reversals are recorded but intentionally not auto-applied to
        # the wallet — surface for manual review in admin.
        return _finalize(event, 'non_purchase', f'transaction type={event.transaction_type or "(missing)"}')
    if not event.invoice_id:
        return _finalize(event, 'no_invoice', 'transaction carries no invoiceNumber')
    if event.amount <= Decimal('0.00'):
        return _finalize(event, 'not_approved', f'non-positive amount {event.amount}')

    try:
        with transaction.atomic():
            # filter().order_by('-id').first() guards MultipleObjectsReturned —
            # helcim_invoice_number has no unique constraint. Match on
            # helcim_invoice_number: payment payloads carry invoiceNumber
            # (e.g. INV1791), never the numeric invoiceId.
            invoice = (
                PreBillingInvoice.objects
                .select_for_update()
                .filter(helcim_invoice_number=event.invoice_id)
                .order_by('-id')
                .first()
            )
            if invoice is None:
                return _finalize(event, 'no_invoice', f'no PreBillingInvoice for invoiceNumber={event.invoice_id}')

            # A parent's first payment is exactly when the wallet should come
            # into existence — get_or_create then re-acquire under lock
            # (REC-02 pattern, race-safe via the unique constraint). Requiring
            # a pre-existing account left first-time payments stranded in
            # no_account (found live 2026-08-27, event INV001028).
            StudentCreditAccount.objects.get_or_create(
                student=invoice.student,
                school=invoice.school,
                defaults={'balance': Decimal('0.00')},
            )
            account = StudentCreditAccount.objects.select_for_update().get(
                student=invoice.student,
                school=invoice.school,
            )
            CreditTransaction.objects.create(
                account=account,
                school=invoice.school,
                type='pre_billing_payment',
                amount=event.amount,
            )
            account.balance += event.amount
            account.save()

            # Coverage is cumulative across credited events for this invoice
            # number, so two partial payments eventually flip the invoice paid.
            prior = (
                HelcimWebhookEvent.objects
                .filter(
                    invoice_id=event.invoice_id,
                    processing_status__in=('credited', 'credited_partial'),
                )
                .exclude(pk=event.pk)
                .aggregate(total=Sum('amount'))['total']
            ) or Decimal('0.00')
            covered = (prior + event.amount) >= invoice.amount
            if covered and invoice.status != 'paid':
                invoice.status = 'paid'
                invoice.save(update_fields=['status', 'updated_at'])

            event.school = invoice.school
            event.processing_status = 'credited' if covered else 'credited_partial'
            event.last_error = '' if covered else (
                f'paid {event.amount} of {invoice.amount} — invoice left {invoice.status}'
            )
            event.processed_at = timezone.now()
            event.save(update_fields=['school', 'processing_status', 'last_error', 'processed_at'])
            if not covered:
                logger.warning(
                    'Partial/mismatched payment on invoice %s: received %s, expected %s (event %s)',
                    invoice.id, event.amount, invoice.amount, event.helcim_transaction_id,
                )
    except StudentCreditAccount.DoesNotExist:
        return _finalize(
            event, 'no_account',
            f'no StudentCreditAccount for invoiceNumber={event.invoice_id}',
        )

    return event


def _finalize(event, processing_status, detail):
    """Stamp a non-credited outcome. Retryable states keep their detail for admin."""
    event.processing_status = processing_status
    event.last_error = detail
    event.processed_at = timezone.now()
    event.save(update_fields=['processing_status', 'last_error', 'processed_at'])
    if processing_status in RETRYABLE_STATES:
        logger.warning('Webhook event %s not reconciled (%s): %s',
                       event.helcim_transaction_id, processing_status, detail)
    else:
        logger.info('Webhook event %s recorded without credit (%s): %s',
                    event.helcim_transaction_id, processing_status, detail)
    return event
