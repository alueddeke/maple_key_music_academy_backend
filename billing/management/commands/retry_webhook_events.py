"""
Re-process Helcim webhook events stuck in a retryable state.

Retryable states (see billing/services/webhook_processing.py):
  pending, enrichment_failed, no_invoice, no_account

Typical causes: Helcim API blip during the secondary GET, webhook arriving
before the invoice row existed, or a missing credit account. Money that
already reached Helcim is reconciled on the next successful run — credit
gating (APPROVED purchase only) still applies.

Usage:
  python manage.py retry_webhook_events            # retry everything retryable
  python manage.py retry_webhook_events --dry-run  # list, change nothing
"""

from django.core.management.base import BaseCommand

from billing.models import HelcimWebhookEvent
from billing.services.webhook_processing import process_webhook_event, RETRYABLE_STATES


class Command(BaseCommand):
    help = 'Re-run credit reconciliation for Helcim webhook events in retryable states.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List retryable events without processing them.',
        )

    def handle(self, *args, **options):
        events = list(
            HelcimWebhookEvent.objects
            .filter(processing_status__in=RETRYABLE_STATES)
            .order_by('received_at')
        )
        if not events:
            self.stdout.write(self.style.SUCCESS('No retryable webhook events.'))
            return

        self.stdout.write(f'{len(events)} retryable event(s):')
        for event in events:
            line = (
                f'  tx={event.helcim_transaction_id} '
                f'state={event.processing_status} '
                f'invoice={event.invoice_id or "-"} '
                f'amount={event.amount} '
                f'received={event.received_at:%Y-%m-%d %H:%M}'
            )
            if options['dry_run']:
                self.stdout.write(line)
                continue
            process_webhook_event(event)
            outcome = event.processing_status
            style = self.style.SUCCESS if outcome.startswith('credited') else self.style.WARNING
            self.stdout.write(f'{line} → {style(outcome)}'
                              + (f' ({event.last_error})' if event.last_error else ''))

        if options['dry_run']:
            self.stdout.write('Dry run — nothing processed.')
        else:
            remaining = HelcimWebhookEvent.objects.filter(
                processing_status__in=RETRYABLE_STATES
            ).count()
            self.stdout.write(self.style.SUCCESS(f'Done. {remaining} event(s) still retryable.'))
