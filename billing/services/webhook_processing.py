"""
billing/services/webhook_processing.py — Helcim webhook credit reconciliation.

Shared by:
  - billing/views/webhooks.py     (live webhook receipt + Helcim retry re-processing)
  - sync_helcim_ach command       (bank payments — polled, Helcim has no bank webhooks)
  - retry_webhook_events command  (manual/scheduled recovery of stuck events)
  - HelcimWebhookEvent admin action

Money-safety rules enforced here:
  - Credit is applied ONLY for transactions with status=APPROVED and
    type=purchase/capture. Declined attempts and refunds/reversals must
    never increase a student's wallet.
  - The invoice is marked paid only when the credited amounts cover
    invoice.amount; a short payment still credits the wallet (the money is
    real) but leaves the invoice open and flags the event credited_partial.
  - The wallet is credited with at most what the invoice still owed
    (MAP-216). Anything above that (e.g. Helcim's card convenience fee) is
    stored on the event as fee_amount and never reaches the balance; a
    payment on an already-covered invoice posts nothing and lands in
    needs_attention.
  - Re-running is safe: terminal states are never re-processed, and the
    'credited*' write happens in the same atomic block that stamps the state.
  - Concurrency (MAP-180): inside the credit transaction the event row is
    re-read under select_for_update() BEFORE the invoice and account locks.
    Lock order is always event → invoice → account. Two deliveries of the
    same event serialize on the event row; the second sees a terminal state
    and returns. CreditTransaction.source_event is unique per event as the
    database backstop, so a credit can never be posted twice for one
    helcim_transaction_id regardless of caller (webhook view, retry command,
    sync command).
  - Helcim HTTP calls stay OUTSIDE transaction.atomic() (STATE.md hard rule).
  - Bank (ACH) events (rail='ach', MAP-217) are never enriched from the card
    API: sync_helcim_ach writes their fields in the canonical vocabulary
    below, and a retry gates on those stored fields. From the event lock
    onward a bank payment follows exactly the card rules (superseded number,
    coverage, cap, paid flip), so a card and a bank payment on one invoice
    are never both credited in full, in either order.
  - Bank returns (MAP-232): a bank payment Helcim later reports as returned
    (NSF, closed account) takes back what it credited, as far as the balance
    allows — a 'reversal' row for min(credit, balance), the rest as an
    informational 'shortfall' — re-opens the invoice, flags the account and
    lands the event in 'returned' (alerting). Same lock order, one atomic
    block; one_reversal_per_webhook_event is the database backstop.
"""

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from billing.metrics import webhook_events_total
from notifications.services import notify_bank_payment_returned

from ..models import (
    CreditTransaction,
    HelcimWebhookEvent,
    PreBillingInvoice,
    StudentCreditAccount,
)
from . import ledger
from .helcim_client import HelcimClient, HelcimAPIError

logger = logging.getLogger(__name__)

# States that a retry (Helcim redelivery, management command, admin action)
# is allowed to re-process. Everything else is terminal.
RETRYABLE_STATES = {'pending', 'enrichment_failed', 'no_invoice', 'no_account'}

# A received payment that did not credit and needs a human — what the
# webhook-failures alert counts (scheduler gauge, MAP-231).
ALERT_STATES = {'enrichment_failed', 'no_invoice', 'no_account', 'needs_attention', 'returned'}

CREDITABLE_TYPES = {'purchase', 'capture'}

# Canonical vocabulary for bank (ACH) events. sync_helcim_ach translates
# Helcim's raw values into these before storing them on the event, so nothing
# in this module depends on Helcim's wire format.
ACH_DEBIT_TYPE = 'ach_debit'
ACH_APPROVED_STATUS = 'APPROVED'
ACH_WAITING_STATUSES = {'PENDING', 'IN_PROGRESS'}
ACH_REFUSED_STATUSES = {'DECLINED', 'CANCELLED'}

PAID_VIA_BY_RAIL = {'card': 'card', 'ach': 'bank'}


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

    written = _process(event)
    if written is not event:
        # The credit path re-read the row under lock and wrote through that
        # copy; bring the caller's instance up to date (the management commands
        # report event.processing_status from the instance they passed in).
        event.refresh_from_db()
    return event


def _gate_ach(event):
    """
    Decide a bank (ACH) event from its stored fields. Returns the finalized
    event when it must not be credited, None when it may enter the credit path.
    """
    if event.transaction_type != ACH_DEBIT_TYPE:
        return _finalize(
            event, 'needs_attention',
            f'bank transaction type={event.transaction_type or "(missing)"} is not a known debit '
            '— not credited, review in admin',
        )
    status = event.transaction_status.upper()
    if status in ACH_WAITING_STATUSES:
        return _finalize(event, 'awaiting_bank', f'bank authorization {status}')
    if status in ACH_REFUSED_STATUSES:
        return _finalize(event, 'not_approved', f'transaction status={event.transaction_status}')
    if status != ACH_APPROVED_STATUS:
        return _finalize(
            event, 'needs_attention',
            f'unknown bank authorization status={event.transaction_status or "(missing)"} '
            '— not credited, review in admin',
        )
    return None


def _process(event):
    if event.rail == 'ach':
        refused = _gate_ach(event)
        if refused is not None:
            return refused
    # Card enrichment — outside any DB transaction. Re-fetch when either the
    # invoice number or the gating fields are missing (legacy rows predate
    # transaction_status).
    elif not event.invoice_id or not event.transaction_status:
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
        # If Helcim reports the fee as its own field, log it for comparison
        # with the computed fee_amount. The cap below is the rule either way.
        reported_fees = {
            key: tx[key] for key in tx
            if 'fee' in key.lower() or 'surcharge' in key.lower()
        }
        if reported_fees:
            logger.info(
                'Webhook event %s: Helcim fee fields %s',
                event.helcim_transaction_id, reported_fees,
            )

    # Gating — strict: anything not an approved purchase/capture never credits.
    tx_status = event.transaction_status.upper()
    tx_type = event.transaction_type.lower()
    if tx_status != 'APPROVED':
        return _finalize(event, 'not_approved', f'transaction status={event.transaction_status or "(missing)"}')
    if event.rail == 'card' and tx_type not in CREDITABLE_TYPES:
        # Refunds/reversals are recorded but intentionally not auto-applied to
        # the wallet — surface for manual review in admin.
        return _finalize(event, 'non_purchase', f'transaction type={event.transaction_type or "(missing)"}')
    if not event.invoice_id:
        return _finalize(event, 'no_invoice', 'transaction carries no invoiceNumber')
    if event.amount <= Decimal('0.00'):
        return _finalize(event, 'not_approved', f'non-positive amount {event.amount}')

    try:
        with transaction.atomic():
            # Lock order: event → invoice → account (MAP-180). The pre-check
            # above ran on an unlocked row; re-read under lock so concurrent
            # deliveries serialize here and every later write goes through
            # the locked copy — the caller-passed instance is stale.
            locked = HelcimWebhookEvent.objects.select_for_update().get(pk=event.pk)
            if locked.processing_status not in RETRYABLE_STATES:
                return locked
            event = locked

            # A number an adjustment superseded (MAP-184) is never credited,
            # whether or not the void succeeded — the parent paid a cancelled
            # invoice and someone has to look. Terminal, so the retry
            # scheduler never picks it up again.
            if PreBillingInvoice.objects.filter(
                previous_helcim_invoice_number=event.invoice_id
            ).exists():
                return _finalize(
                    event, 'needs_attention',
                    f'payment on superseded invoiceNumber={event.invoice_id} — not credited, review in admin',
                )

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
            # Coverage is cumulative across credited events for this invoice
            # number, so two partial payments eventually flip the invoice paid.
            # Sum what was credited (amount − fee_amount), not gross: a fee on
            # an earlier payment never reduces what the invoice still owes.
            prior = (
                HelcimWebhookEvent.objects
                .filter(
                    invoice_id=event.invoice_id,
                    processing_status__in=('credited', 'credited_partial'),
                )
                .exclude(pk=event.pk)
                .aggregate(total=Sum(F('amount') - F('fee_amount')))['total']
            ) or Decimal('0.00')

            # The wallet gets at most what the invoice still owed (MAP-216).
            # Anything above that — e.g. Helcim's card convenience fee — is
            # recorded on the event and never reaches the balance.
            remaining = max(invoice.amount - prior, Decimal('0.00'))
            credit = min(event.amount, remaining)
            fee = event.amount - credit
            if credit == Decimal('0.00'):
                return _finalize(
                    event, 'needs_attention',
                    f'payment on an already-covered invoice invoiceNumber={event.invoice_id} '
                    f'— {event.amount} not credited, review in admin',
                )
            event.fee_amount = fee
            if fee > Decimal('0.00'):
                logger.info(
                    'Webhook event %s: received %s, credited %s, fee %s (invoice %s)',
                    event.helcim_transaction_id, event.amount, credit, fee, invoice.id,
                )

            # Savepoint: an IntegrityError on one_credit_per_webhook_event must
            # not poison the outer atomic block. ledger.post is the single
            # balance writer (MAP-186): it writes the row and moves the
            # balance together, so a rejected row leaves the balance alone.
            try:
                with transaction.atomic():
                    ledger.post(
                        account,
                        type='pre_billing_payment',
                        amount=credit,
                        source_event=event,
                    )
            except IntegrityError:
                # The credit for this event was already posted — finalize as
                # credited WITHOUT touching the balance.
                logger.warning(
                    'Credit already posted for webhook event %s; not posting again',
                    event.helcim_transaction_id,
                )
                event.school = invoice.school
                event.processing_status = 'credited'
                event.last_error = ''
                event.processed_at = timezone.now()
                event.save(update_fields=[
                    'school', 'fee_amount', 'processing_status', 'last_error', 'processed_at',
                ])
                webhook_events_total.labels(outcome='credited').inc()
                return event

            covered = (prior + credit) >= invoice.amount
            if covered and invoice.status != 'paid':
                invoice.status = 'paid'
                invoice.paid_via = PAID_VIA_BY_RAIL[event.rail]
                invoice.save(update_fields=['status', 'paid_via', 'updated_at'])

            event.school = invoice.school
            event.processing_status = 'credited' if covered else 'credited_partial'
            event.last_error = '' if covered else (
                f'credited {prior + credit} of {invoice.amount} — invoice left {invoice.status}'
            )
            event.processed_at = timezone.now()
            event.save(update_fields=[
                'school', 'fee_amount', 'processing_status', 'last_error', 'processed_at',
            ])
            webhook_events_total.labels(outcome=event.processing_status).inc()
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
    webhook_events_total.labels(outcome=processing_status).inc()
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


def apply_bank_return(event):
    """
    Apply a bank return reported by Helcim to an ACH event (MAP-232).

    Credited event: reverse what it credited (amount − fee_amount) — a
    'reversal' row for as much as the balance holds, the remainder as an
    informational 'shortfall' row on the invoice — flag the account, set the
    invoice back to adjusted (revision > 0) or sent and clear paid_via.
    Never-credited event: no ledger row. Either way the event lands in
    'returned' and management gets a bell notification after commit.

    Idempotent: an event already 'returned' is left alone. Returns the event
    as stored.
    """
    with transaction.atomic():
        # Lock order: event → invoice → account (MAP-180).
        locked = HelcimWebhookEvent.objects.select_for_update().get(pk=event.pk)
        if locked.processing_status == 'returned':
            return locked
        invoice = (
            PreBillingInvoice.objects
            .select_for_update()
            .filter(helcim_invoice_number=locked.invoice_id)
            .order_by('-id')
            .first()
        ) if locked.invoice_id else None
        # "Credited" is read from the ledger, not the status: the credit row
        # is what has to be taken back, whatever state the event is in now.
        credited = CreditTransaction.objects.filter(
            source_event=locked, type='pre_billing_payment',
        ).exists()
        if not credited:
            detail = 'bank payment returned — it was never credited, no ledger row'
            reversed_amount = shortfall_amount = Decimal('0.00')
        elif invoice is None:
            if locked.processing_status == 'needs_attention':
                return locked  # already flagged; re-stamping would keep the alert firing
            return _finalize(
                locked, 'needs_attention',
                f'bank payment returned but no PreBillingInvoice for invoiceNumber='
                f'{locked.invoice_id or "(missing)"} — wallet not reversed, review in admin',
            )
        else:
            account = StudentCreditAccount.objects.select_for_update().get(
                student=invoice.student, school=invoice.school,
            )
            reversal = locked.amount - locked.fee_amount
            reversed_amount = min(reversal, account.balance)
            shortfall_amount = reversal - reversed_amount
            if reversed_amount > Decimal('0.00'):
                ledger.post(account, type='reversal', amount=reversed_amount, source_event=locked)
            if shortfall_amount > Decimal('0.00'):
                ledger.post(account, type='shortfall', amount=shortfall_amount, source_invoice=invoice)
            StudentCreditAccount.objects.filter(pk=account.pk).update(needs_attention=True)
            invoice.status = 'adjusted' if invoice.revision > 0 else 'sent'
            invoice.paid_via = ''
            invoice.save(update_fields=['status', 'paid_via', 'updated_at'])
            detail = (
                f'bank payment returned — reversed {reversed_amount} of {reversal} credited'
                + (f', {shortfall_amount} not covered by the balance' if shortfall_amount else '')
                + f'; invoice {invoice.id} back to {invoice.status}'
            )

        webhook_events_total.labels(outcome='returned').inc()
        locked.processing_status = 'returned'
        locked.last_error = detail
        locked.processed_at = timezone.now()
        locked.save(update_fields=['processing_status', 'last_error', 'processed_at'])
        logger.warning('Webhook event %s: %s', locked.helcim_transaction_id, detail)

        student = invoice.student if invoice is not None else None
        transaction.on_commit(
            lambda: _notify_return(locked, student, reversed_amount, shortfall_amount)
        )
    return locked


def flag_unknown_bank_clearing(event, raw_clearing):
    """
    A bank return list row carried a statusClearing value the app does not
    know (MAP-232): move no money, land the event in needs_attention so a
    person looks. Events already returned or needs_attention are left alone
    (re-stamping them would keep the 15-minute alert firing every tick).
    """
    with transaction.atomic():
        locked = HelcimWebhookEvent.objects.select_for_update().get(pk=event.pk)
        if locked.processing_status in ('returned', 'needs_attention'):
            return locked
        return _finalize(
            locked, 'needs_attention',
            f'unknown bank clearing status={raw_clearing} — no money moved, review in admin',
        )


def _notify_return(event, student, reversed_amount, shortfall_amount):
    # Never let a notification failure surface: the return is already
    # committed (mirrors notifications/signals.py idiom).
    try:
        notify_bank_payment_returned(event, student, reversed_amount, shortfall_amount)
    except Exception:  # noqa: BLE001
        logger.exception(
            'Failed to create bank-return notification for webhook event %s',
            event.helcim_transaction_id,
        )
