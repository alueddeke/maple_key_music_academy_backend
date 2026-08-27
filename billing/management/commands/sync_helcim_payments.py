"""
Pull-based reconciliation for Helcim payments whose webhooks never arrived.

Webhooks are the primary path; Helcim retries failures for ~10 hours. This
command covers everything past that: endpoint down longer than the retry
window, webhook misconfiguration, or a dev tunnel that wasn't running when
a test payment was made.

Lists recent card transactions from the Helcim API, creates a webhook-event
row for any transaction the app has never seen, and runs the standard
credit reconciliation on it (same gating: APPROVED purchases only; declines
and refunds are recorded but never credited).

Usage:
  python manage.py sync_helcim_payments               # sync latest 50
  python manage.py sync_helcim_payments --limit 200
  python manage.py sync_helcim_payments --dry-run     # list, change nothing

Safe to run repeatedly (idempotent via helcim_transaction_id) and safe to
cron alongside retry_webhook_events.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from billing.models import HelcimWebhookEvent
from billing.services.helcim_client import HelcimClient, HelcimAPIError
from billing.services.webhook_processing import process_webhook_event


class Command(BaseCommand):
    help = 'Reconcile Helcim card transactions whose webhooks never arrived.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=50,
            help='How many recent card transactions to fetch (default 50).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List unseen transactions without creating or processing anything.',
        )

    def handle(self, *args, **options):
        client = HelcimClient()
        try:
            transactions = client.list_card_transactions(limit=options['limit'])
        except HelcimAPIError as e:
            self.stderr.write(self.style.ERROR(f'Helcim API error: {e}'))
            return

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
            f'{len(transactions)} transaction(s) fetched, '
            f'{len(seen)} already recorded, {len(unseen)} new.'
        )

        for tx in unseen:
            tx_id = str(tx['transactionId'])
            line = (
                f'  tx={tx_id} invoice={tx.get("invoiceNumber", "-")} '
                f'amount={tx.get("amount")} status={tx.get("status")} type={tx.get("type")}'
            )
            if options['dry_run']:
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
                    'school': None,
                },
            )
            if created:
                process_webhook_event(event)
            outcome = event.processing_status
            style = self.style.SUCCESS if outcome.startswith('credited') else self.style.WARNING
            self.stdout.write(f'{line} → {style(outcome)}'
                              + (f' ({event.last_error})' if event.last_error else ''))

        if options['dry_run']:
            self.stdout.write('Dry run — nothing created.')
