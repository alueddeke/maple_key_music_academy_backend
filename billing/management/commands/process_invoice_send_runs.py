"""
Send-run worker (batch-queue wave): drains InvoiceSendRun items off the
request workers. Runs as its own container (see docker repo `worker` service)
so a crash here can never take down the API, and vice versa.

Concurrency model: items are claimed one at a time with
select_for_update(skip_locked) in FIFO order, so running N copies of this
command is safe — parallelism is an ops decision, not a code change. The
invoice-level draft->sending conditional UPDATE inside send_single_invoice
remains the last double-send guard.

Retry policy: transient Helcim failures (network / 5xx) retry in place up to
MAX_ATTEMPTS with a short backoff; validation-class failures ($0 invoice,
missing contact, non-draft invoice) fail or skip immediately — retrying can't
fix them.
"""
import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from billing.models import InvoiceSendItem, InvoiceSendRun
from billing.services.helcim_client import HelcimAPIError
from billing.services.invoice_sending import InvoiceSendConflict, send_single_invoice

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2  # attempt n sleeps n * this before retrying
IDLE_SLEEP_SECONDS = 5
STALE_SENDING_MINUTES = 10


def _is_transient(exc):
    """Network errors and Helcim 5xx are worth retrying; 4xx/validation are not."""
    if isinstance(exc, HelcimAPIError):
        return exc.status_code is None or exc.status_code >= 500
    return False


class Command(BaseCommand):
    help = 'Drain queued InvoiceSendRuns: send each snapshotted invoice via Helcim.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once', action='store_true',
            help='Process until the queue is empty, then exit (tests/cron).',
        )

    def handle(self, *args, **options):
        self._stop = False
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)

        self._recover_stale_items()
        logger.info('Send-run worker started (once=%s)', options['once'])

        while not self._stop:
            item = self._claim_next_item()
            if item is None:
                if options['once']:
                    break
                time.sleep(IDLE_SLEEP_SECONDS)
                continue
            self._process_item(item)
            self._finish_run_if_drained(item.run_id)

        logger.info('Send-run worker stopped')

    def _request_stop(self, signum, frame):
        # Finish the current item, then exit — compose stop_grace_period
        # gives us the window.
        logger.info('Send-run worker received signal %s — stopping after current item', signum)
        self._stop = True

    def _recover_stale_items(self):
        """
        Re-queue items a dead worker left in 'sending'. The invoice-level
        claim in send_single_invoice still prevents a double Helcim send if
        the old worker got that far — the retry will surface
        InvoiceSendConflict and the item is skipped, not re-sent.
        """
        cutoff = timezone.now() - timezone.timedelta(minutes=STALE_SENDING_MINUTES)
        # updated_at doesn't exist on items; conservative proxy: any 'sending'
        # item at startup is orphaned — no other worker instance is expected,
        # and a concurrent healthy worker holds a row lock we must not steal,
        # so filter to runs older than the cutoff as the safety margin.
        recovered = InvoiceSendItem.objects.filter(
            status='sending', run__created_at__lt=cutoff,
        ).update(status='pending')
        if recovered:
            logger.warning('Recovered %s orphaned sending item(s) back to pending', recovered)

    def _claim_next_item(self):
        """Atomically claim the FIFO-next pending item across live runs."""
        with transaction.atomic():
            item = (
                InvoiceSendItem.objects
                .select_for_update(skip_locked=True, of=('self',))
                .filter(status='pending', run__status__in=('queued', 'running'))
                .order_by('run_id', 'position')
                .first()
            )
            if item is None:
                return None
            item.status = 'sending'
            item.save(update_fields=['status'])
            InvoiceSendRun.objects.filter(pk=item.run_id, status='queued').update(
                status='running', started_at=timezone.now()
            )
            return item

    def _process_item(self, item):
        invoice = item.invoice
        if invoice.status != 'draft':
            # Sent individually (or otherwise moved on) after the snapshot —
            # nothing to do, and not a failure worth alarming on.
            self._finalize_item(item, 'skipped', f'Invoice status is {invoice.status}, not draft.')
            return

        attempt = 0
        while True:
            attempt += 1
            InvoiceSendItem.objects.filter(pk=item.pk).update(attempts=attempt)
            try:
                send_single_invoice(invoice, invoice.school)
            except Exception as exc:  # noqa: BLE001 — every failure must land on the item row
                if _is_transient(exc) and attempt < MAX_ATTEMPTS and not self._stop:
                    logger.warning(
                        'Send item %s attempt %s/%s failed transiently: %s',
                        item.pk, attempt, MAX_ATTEMPTS, exc,
                    )
                    time.sleep(attempt * RETRY_BACKOFF_SECONDS)
                    invoice.refresh_from_db()
                    continue
                status = 'skipped' if isinstance(exc, InvoiceSendConflict) else 'failed'
                logger.error('Send item %s (invoice %s) %s: %s', item.pk, invoice.pk, status, exc)
                self._finalize_item(item, status, str(exc))
                return
            self._finalize_item(item, 'sent', '')
            return

    def _finalize_item(self, item, status, error):
        with transaction.atomic():
            InvoiceSendItem.objects.filter(pk=item.pk).update(
                status=status, last_error=error, finished_at=timezone.now()
            )
            if status == 'sent':
                InvoiceSendRun.objects.filter(pk=item.run_id).update(
                    sent_count=F('sent_count') + 1
                )
            elif status == 'failed':
                InvoiceSendRun.objects.filter(pk=item.run_id).update(
                    failed_count=F('failed_count') + 1
                )

    def _finish_run_if_drained(self, run_id):
        remaining = InvoiceSendItem.objects.filter(
            run_id=run_id, status__in=('pending', 'sending')
        ).exists()
        if not remaining:
            updated = InvoiceSendRun.objects.filter(
                pk=run_id, status__in=('queued', 'running')
            ).update(status='done', finished_at=timezone.now())
            if updated:
                logger.info('Send run %s done', run_id)
