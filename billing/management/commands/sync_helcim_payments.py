"""
Pull-based reconciliation for Helcim payments whose webhooks never arrived.

Webhooks are the primary path; Helcim retries failures for ~10 hours. This
command covers everything past that: endpoint down longer than the retry
window, webhook misconfiguration, or a dev tunnel that wasn't running when
a test payment was made.

Per School (MAP-154, D4): lists card transactions with that school's Helcim
client from its checkpoint date (School.helcim_last_synced_at; 30 days back
on the first run), creates a webhook-event row for any transaction the app
has never seen, runs the standard credit reconciliation on it (same gating:
APPROVED purchases only; declines and refunds are recorded but never
credited), and advances the checkpoint to the newest dateCreated seen.
`dateFrom` is day-granular, so rows on the checkpoint day are fetched again
and dropped client-side when older than the checkpoint.

Usage:
  python manage.py sync_helcim_payments               # every school
  python manage.py sync_helcim_payments --dry-run     # list, change nothing

Safe to run repeatedly (idempotent via helcim_transaction_id); run_scheduler
runs it once a day.
"""

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import HelcimWebhookEvent, School
from billing.services.helcim_client import HelcimClient, HelcimAPIError
from billing.services.webhook_processing import process_webhook_event

# Helcim honours `limit` on /v2/card-transactions but its default page size is
# unknown — always send one (R10). Big enough for a day of a single school.
SYNC_PAGE_LIMIT = 1000
FIRST_RUN_LOOKBACK_DAYS = 30


def parse_date_created(value):
    """
    Helcim dateCreated ('YYYY-MM-DD HH:MM:SS', no zone) → aware datetime.
    Read as UTC: the checkpoint is derived from the same field, so filter and
    checkpoint stay self-consistent whatever Helcim's wall clock is.
    """
    if not value:
        return None
    try:
        return datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S').replace(tzinfo=dt_timezone.utc)
    except ValueError:
        return None


class Command(BaseCommand):
    help = 'Reconcile Helcim card transactions whose webhooks never arrived (every school).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List unseen transactions without creating or processing anything.',
        )

    def handle(self, *args, **options):
        for school in School.objects.order_by('id'):
            self._sync_school(school, options['dry_run'])
        if options['dry_run']:
            self.stdout.write('Dry run — nothing created.')

    def _sync_school(self, school, dry_run):
        checkpoint = school.helcim_last_synced_at
        if checkpoint is not None:
            date_from = checkpoint.date()
        else:
            date_from = (timezone.now() - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)).date()

        # Per-school client: blank school fields fall back to the env
        # credentials (prod's single school today) — R9.
        client = HelcimClient(school=school)
        try:
            transactions = client.list_card_transactions(
                date_from=date_from, limit=SYNC_PAGE_LIMIT,
            )
        except HelcimAPIError as e:
            self.stderr.write(self.style.ERROR(
                f'[{school.name}] Helcim API error: {e} — checkpoint unchanged'
            ))
            return

        if checkpoint is not None:
            # dateFrom is day-granular: drop the checkpoint day's already-seen
            # rows. Rows without a parseable dateCreated are kept (never drop
            # money on a missing field).
            transactions = [
                t for t in transactions
                if (parse_date_created(t.get('dateCreated')) or checkpoint) >= checkpoint
            ]

        seen = set(
            HelcimWebhookEvent.objects
            .filter(helcim_transaction_id__in=[
                str(t.get('transactionId', '')) for t in transactions
            ])
            .values_list('helcim_transaction_id', flat=True)
        )
        unseen = [
            t for t in transactions
            if str(t.get('transactionId', '')) and str(t.get('transactionId', '')) not in seen
        ]
        self.stdout.write(
            f'[{school.name}] from {date_from}: {len(transactions)} transaction(s) fetched, '
            f'{len(seen)} already recorded, {len(unseen)} new.'
        )

        for tx in unseen:
            tx_id = str(tx['transactionId'])
            line = (
                f'  tx={tx_id} invoice={tx.get("invoiceNumber", "-")} '
                f'amount={tx.get("amount")} status={tx.get("status")} type={tx.get("type")}'
            )
            if dry_run:
                self.stdout.write(line)
                continue

            event, created = HelcimWebhookEvent.objects.get_or_create(
                helcim_transaction_id=tx_id,
                defaults={
                    # Mark the origin — this row was pulled by sync, not pushed
                    # by a webhook. Enrichment fields fill in during processing.
                    'raw_payload': {'id': tx_id, 'type': 'cardTransaction', 'source': 'sync'},
                    'invoice_id': '',
                    'amount': Decimal('0.00'),
                    'school': school,
                },
            )
            if created:
                process_webhook_event(event)
            outcome = event.processing_status
            style = self.style.SUCCESS if outcome.startswith('credited') else self.style.WARNING
            self.stdout.write(f'{line} → {style(outcome)}'
                              + (f' ({event.last_error})' if event.last_error else ''))

        if dry_run:
            return

        # Advance the checkpoint only after a successful page; rows without a
        # parseable dateCreated do not move it.
        newest = max(
            (d for d in (parse_date_created(t.get('dateCreated')) for t in transactions) if d),
            default=None,
        )
        if newest is not None and (checkpoint is None or newest > checkpoint):
            School.objects.filter(pk=school.pk).update(helcim_last_synced_at=newest)
