"""
Poll-based reconciliation for bank (ACH/EFT) payments made on the Helcim
payment page (MAP-217).

Helcim sends webhooks for card transactions only, so a parent who pays by
bank is invisible to the webhook path. This command is the bank rail's only
entry point: per School it lists that school's bank transactions from its
ACH checkpoint (School.helcim_ach_last_synced_at; 30 days back on the first
run), records each one as a HelcimWebhookEvent with rail='ach', and runs the
standard credit reconciliation on it — from the event lock onward the rules
are the card rules (superseded number, coverage, cap, paid flip).

Outcomes by bank authorization status:
  APPROVED               → credited through the standard path (paid_via='bank')
  PENDING / IN_PROGRESS  → awaiting_bank: no credit, no alert; read again on
                           every run and processed when it resolves
  DECLINED / CANCELLED   → not_approved
  anything else          → needs_attention (alerts; a person looks)

The checkpoint never moves past the oldest transaction still awaiting the
bank, so every run lists that transaction again without a second endpoint.
`startDate` is day-granular: rows on the checkpoint day are fetched again and
dropped client-side when older than the checkpoint.

Usage:
  python manage.py sync_helcim_ach               # every school
  python manage.py sync_helcim_ach --dry-run     # list, change nothing

Safe to run repeatedly (idempotent via rail + helcim_transaction_id);
run_scheduler runs it every 15 minutes.
"""

import logging
from collections import namedtuple
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.management.commands.sync_helcim_payments import (
    FIRST_RUN_LOOKBACK_DAYS,
    parse_date_created,
)
from billing.models import HelcimWebhookEvent, School
from billing.services.helcim_client import ACH_PAGE_LIMIT, HelcimAPIError, HelcimClient
from billing.services.webhook_processing import (
    ACH_APPROVED_STATUS,
    ACH_DEBIT_TYPE,
    ACH_REFUSED_STATUSES,
    ACH_WAITING_STATUSES,
    process_webhook_event,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HELCIM ACH ROW SHAPE — the one place that knows Helcim's wire format.
#
# Everything in this block comes from Helcim's documentation (devdocs
# "ach-payments" and the getmanyachtransactions reference) and from tier-2
# support (thread 7VNGKG-KZXN5), NOT from an observed row: no bank transaction
# existed on the test or the production account on 2026-10-05 (MAP-270).
#
# When a real row or Helcim's answer arrives, correct the keys and tables here
# and the sample row in tests/unit/billing/test_sync_helcim_ach.py (`ach_row`).
# Nothing below this block, and nothing in webhook_processing.py, reads a raw
# Helcim value.
# ---------------------------------------------------------------------------
ROW_ID_KEY = 'id'
ROW_INVOICE_NUMBER_KEY = 'invoiceNumber'
ROW_AMOUNT_KEY = 'amount'
ROW_DATE_CREATED_KEY = 'dateCreated'          # 'YYYY-MM-DD HH:MM:SS', as on card rows
ROW_STATUS_AUTH_KEY = 'statusAuth'
ROW_TRANSACTION_TYPE_KEY = 'transactionType'

# statusAuth is an integer in responses (the list filter takes the names).
# Documented: 1, 2, 4, 5. No integer is documented for IN_PROGRESS; an
# unlisted value lands in needs_attention until it is added here.
STATUS_AUTH_NAMES = {
    1: 'APPROVED',
    2: 'DECLINED',
    4: 'CANCELLED',
    5: 'PENDING',
}

# transactionType values that are a debit of the payer's bank account (a
# payment). The documented example payment carries 1; the rest of the
# vocabulary is unknown, so any other value lands in needs_attention.
DEBIT_TRANSACTION_TYPES = {1}
# ---------------------------------------------------------------------------

KNOWN_STATUS_NAMES = {ACH_APPROVED_STATUS} | ACH_WAITING_STATUSES | ACH_REFUSED_STATUSES
UNKNOWN_PREFIX = 'UNKNOWN:'

# Safety stop for the page loop: 40 pages × 125 rows. Hitting it is treated as
# an API error (checkpoint unchanged), never as "the list ended".
MAX_PAGES = 40
AWAITING_WARN_AFTER = timedelta(days=7)

BankPayment = namedtuple('BankPayment', 'tx_id invoice_number amount created status kind')


def canonical_status(raw):
    """Helcim statusAuth (integer, numeric string or name) → canonical name, or UNKNOWN:<raw>."""
    if isinstance(raw, str) and raw.strip().upper() in KNOWN_STATUS_NAMES:
        return raw.strip().upper()
    try:
        # bool is an int in Python; True must not read as status 1.
        return STATUS_AUTH_NAMES[int(raw)] if not isinstance(raw, bool) else f'{UNKNOWN_PREFIX}{raw}'
    except (TypeError, ValueError, KeyError):
        return f'{UNKNOWN_PREFIX}{raw}'


def canonical_kind(raw):
    """Helcim transactionType → ACH_DEBIT_TYPE for a payment, or UNKNOWN:<raw>."""
    try:
        if not isinstance(raw, bool) and int(raw) in DEBIT_TRANSACTION_TYPES:
            return ACH_DEBIT_TYPE
    except (TypeError, ValueError):
        pass
    return f'{UNKNOWN_PREFIX}{raw}'


def read_row(row):
    """
    One Helcim ACH transaction dict → BankPayment in the app's vocabulary.
    tx_id is '' and amount is None when the row cannot be read; the caller
    skips such a row and leaves the checkpoint where it is.
    """
    raw_id = row.get(ROW_ID_KEY)
    try:
        # T-18-C7: Decimal(str(...)) — never float() for money (CONVENTIONS.md)
        amount = Decimal(str(row.get(ROW_AMOUNT_KEY)))
    except InvalidOperation:
        amount = None
    if amount is not None and not amount.is_finite():
        amount = None
    status_field = HelcimWebhookEvent._meta.get_field('transaction_status')
    kind_field = HelcimWebhookEvent._meta.get_field('transaction_type')
    return BankPayment(
        tx_id='' if raw_id in (None, '') else str(raw_id),
        invoice_number=str(row.get(ROW_INVOICE_NUMBER_KEY) or ''),
        amount=amount,
        created=parse_date_created(row.get(ROW_DATE_CREATED_KEY)),
        status=canonical_status(row.get(ROW_STATUS_AUTH_KEY))[:status_field.max_length],
        kind=canonical_kind(row.get(ROW_TRANSACTION_TYPE_KEY))[:kind_field.max_length],
    )


class Command(BaseCommand):
    help = 'Reconcile bank (ACH/EFT) payments made on the Helcim payment page (every school).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List unseen bank transactions without creating or processing anything.',
        )

    def handle(self, *args, **options):
        for school in School.objects.order_by('id'):
            self._sync_school(school, options['dry_run'])
        if options['dry_run']:
            self.stdout.write('Dry run — nothing created.')

    def _fetch(self, client, date_from):
        rows = []
        for page in range(1, MAX_PAGES + 1):
            batch = client.list_ach_transactions(
                limit=ACH_PAGE_LIMIT, date_from=date_from, page=page,
            )
            rows.extend(batch)
            if len(batch) < ACH_PAGE_LIMIT:
                return rows
        raise HelcimAPIError(
            f'more than {MAX_PAGES} pages of bank transactions from {date_from}',
            status_code=None,
        )

    def _sync_school(self, school, dry_run):
        checkpoint = school.helcim_ach_last_synced_at
        if checkpoint is not None:
            date_from = checkpoint.date()
        else:
            date_from = (timezone.now() - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)).date()

        # Per-school client: blank school fields fall back to the env
        # credentials (prod's single school today) — R9.
        client = HelcimClient(school=school)
        try:
            rows = self._fetch(client, date_from)
        except HelcimAPIError as e:
            self.stderr.write(self.style.ERROR(
                f'[{school.name}] Helcim API error: {e} — ACH checkpoint unchanged'
            ))
            return

        payments = [read_row(row) for row in rows]
        if checkpoint is not None:
            # startDate is day-granular: drop the checkpoint day's rows older
            # than the checkpoint. Rows without a parseable dateCreated are
            # kept (never drop money on a missing field).
            payments = [p for p in payments if (p.created or checkpoint) >= checkpoint]

        recorded = {
            event.helcim_transaction_id: event
            for event in HelcimWebhookEvent.objects.filter(
                rail='ach', helcim_transaction_id__in=[p.tx_id for p in payments if p.tx_id],
            )
        }
        new_count = sum(1 for p in payments if p.tx_id and p.tx_id not in recorded)
        self.stdout.write(
            f'[{school.name}] from {date_from}: {len(payments)} bank transaction(s) fetched, '
            f'{len(recorded)} already recorded, {new_count} new.'
        )

        unreadable = 0
        waiting = []
        for payment in payments:
            if not payment.tx_id or payment.amount is None:
                unreadable += 1
                self.stderr.write(self.style.ERROR(
                    f'[{school.name}] unreadable bank transaction '
                    f'(id={payment.tx_id or "missing"}, amount readable={payment.amount is not None})'
                ))
                continue
            event = self._reconcile(school, payment, recorded.get(payment.tx_id), dry_run)
            if event is not None and event.processing_status == 'awaiting_bank':
                waiting.append(payment)

        self._warn_stale(school)
        if dry_run:
            return
        self._advance_checkpoint(school, checkpoint, payments, waiting, unreadable)

    def _reconcile(self, school, payment, event, dry_run):
        """Record or re-read one bank payment; returns its event (None on a dry-run new row)."""
        line = (
            f'  ach={payment.tx_id} invoice={payment.invoice_number or "-"} '
            f'amount={payment.amount} status={payment.status} type={payment.kind}'
        )
        if event is None:
            if dry_run:
                self.stdout.write(line)
                return None
            event, created = HelcimWebhookEvent.objects.get_or_create(
                rail='ach',
                helcim_transaction_id=payment.tx_id,
                defaults={
                    # Origin marker only — no bank data is stored (PCI/privacy).
                    'raw_payload': {'id': payment.tx_id, 'rail': 'ach', 'source': 'sync'},
                    'invoice_id': payment.invoice_number,
                    'amount': payment.amount,
                    'transaction_status': payment.status,
                    'transaction_type': payment.kind,
                    'school': school,
                },
            )
            if created:
                process_webhook_event(event)
        elif event.processing_status != 'awaiting_bank':
            return event  # settled on an earlier run
        elif dry_run or event.transaction_status == payment.status:
            return event  # still waiting on the bank — nothing to write
        else:
            # The bank answered: store the new status and run the gate again.
            # awaiting_bank is not a retryable state, so hand it back as pending.
            event.transaction_status = payment.status
            event.processing_status = 'pending'
            event.save(update_fields=['transaction_status', 'processing_status'])
            process_webhook_event(event)

        outcome = event.processing_status
        style = self.style.SUCCESS if outcome.startswith('credited') else self.style.WARNING
        self.stdout.write(f'{line} → {style(outcome)}'
                          + (f' ({event.last_error})' if event.last_error else ''))
        return event

    def _warn_stale(self, school):
        stale = HelcimWebhookEvent.objects.filter(
            rail='ach',
            school=school,
            processing_status='awaiting_bank',
            received_at__lt=timezone.now() - AWAITING_WARN_AFTER,
        )
        for event in stale:
            logger.warning(
                'Bank payment %s (invoice %s) still awaiting the bank %s days after it was first seen',
                event.helcim_transaction_id, event.invoice_id or '-', AWAITING_WARN_AFTER.days,
            )

    def _advance_checkpoint(self, school, checkpoint, payments, waiting, unreadable):
        if unreadable:
            self.stderr.write(self.style.ERROR(
                f'[{school.name}] {unreadable} unreadable bank transaction(s) — ACH checkpoint unchanged'
            ))
            return
        if waiting:
            # Hold at the oldest transaction the bank has not answered, so the
            # next run lists it again. One without a date cannot be held → stay.
            if any(p.created is None for p in waiting):
                return
            target = min(p.created for p in waiting)
        else:
            target = max((p.created for p in payments if p.created), default=None)
        if target is not None and (checkpoint is None or target > checkpoint):
            School.objects.filter(pk=school.pk).update(helcim_ach_last_synced_at=target)
