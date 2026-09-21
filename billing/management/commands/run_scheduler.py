"""
Unattended reconciliation scheduler (MAP-154). Runs as its own container
(`maple-key-scheduler` in prod, `scheduler` in dev compose) so nothing here
can take down the API or the send-run worker.

Each tick:
  - every 15 minutes: retry_webhook_events (first tick runs it at startup, so
    a deploy flushes stuck events at once)
  - once per UTC day at/after 03:00: sync_helcim_payments (a start after
    03:00 syncs immediately — a deploy never skips a day; sync is idempotent)
  - refresh maplekey_webhook_events_unresolved_1h (retryable events received
    more than an hour ago) and maplekey_scheduler_last_tick_timestamp

Metrics are served on SCHEDULER_METRICS_PORT (default 9103) for the
'scheduler' Prometheus job; the webhook-unresolved alert fires on the gauge
and on NoData (scheduler down). A command that raises is logged and the
loop continues — the scheduler never dies on a Helcim outage.
"""
import logging
import os
import signal
import time
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from prometheus_client import Gauge, start_http_server

from billing.models import HelcimWebhookEvent
from billing.services.webhook_processing import RETRYABLE_STATES

logger = logging.getLogger(__name__)

RETRY_INTERVAL = timedelta(minutes=15)
SYNC_HOUR_UTC = 3
UNRESOLVED_AFTER = timedelta(hours=1)
TICK_SLEEP_SECONDS = 60

webhook_events_unresolved_1h = Gauge(
    'maplekey_webhook_events_unresolved_1h',
    'Helcim webhook events still in a retryable state more than 1h after receipt',
)
scheduler_last_tick_timestamp = Gauge(
    'maplekey_scheduler_last_tick_timestamp',
    'Unix time of the last scheduler tick',
)


class Command(BaseCommand):
    help = 'Run retry_webhook_events every 15 min and sync_helcim_payments daily; export the unresolved gauge.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once', action='store_true',
            help='Run a single tick and exit (tests/cron); no metrics server.',
        )

    def handle(self, *args, **options):
        self._stop = False
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)
        self._next_retry_at = None   # None → due now
        self._last_sync_day = None

        if not options['once']:
            start_http_server(int(os.environ.get('SCHEDULER_METRICS_PORT', '9103')))
        logger.info('Scheduler started (once=%s)', options['once'])

        while not self._stop:
            self._tick()
            if options['once']:
                break
            time.sleep(TICK_SLEEP_SECONDS)

        logger.info('Scheduler stopped')

    def _request_stop(self, signum, frame):
        logger.info('Scheduler received signal %s — stopping after current tick', signum)
        self._stop = True

    def _tick(self):
        now = timezone.now()
        if self._next_retry_at is None or now >= self._next_retry_at:
            self._run('retry_webhook_events')
            self._next_retry_at = now + RETRY_INTERVAL
        if now.hour >= SYNC_HOUR_UTC and self._last_sync_day != now.date():
            self._run('sync_helcim_payments')
            self._last_sync_day = now.date()
        self._refresh_gauges(now)

    def _run(self, command):
        try:
            call_command(command, stdout=self.stdout, stderr=self.stderr)
        except Exception:  # noqa: BLE001 — the loop must outlive any one failure
            logger.exception('Scheduler: %s raised; continuing', command)

    def _refresh_gauges(self, now):
        unresolved = HelcimWebhookEvent.objects.filter(
            processing_status__in=RETRYABLE_STATES,
            received_at__lt=now - UNRESOLVED_AFTER,
        ).count()
        webhook_events_unresolved_1h.set(unresolved)
        scheduler_last_tick_timestamp.set(now.timestamp())
        if unresolved:
            logger.warning('%s webhook event(s) unresolved for more than 1h', unresolved)
