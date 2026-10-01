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
    more than an hour ago), maplekey_webhook_events_failed_15m (events that
    landed in an alert state in the last 15 min — the webhook-failures alert,
    MAP-231) and maplekey_scheduler_last_tick_timestamp

Metrics are served on SCHEDULER_METRICS_PORT (default 9103) for the
'scheduler' Prometheus job; the webhook-unresolved alert fires on the gauge
and on NoData (scheduler down). A command that raises is logged and the
loop continues — the scheduler never dies on a Helcim outage.
"""
import logging
import os
import signal
import threading
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from prometheus_client import Gauge, start_http_server

from billing.models import HelcimWebhookEvent
from billing.services.webhook_processing import ALERT_STATES, RETRYABLE_STATES

logger = logging.getLogger(__name__)

RETRY_INTERVAL = timedelta(minutes=15)
SYNC_HOUR_UTC = 3
UNRESOLVED_AFTER = timedelta(hours=1)
ALERT_WINDOW = timedelta(minutes=15)
TICK_SLEEP_SECONDS = 60

webhook_events_unresolved_1h = Gauge(
    'maplekey_webhook_events_unresolved_1h',
    'Helcim webhook events still in a retryable state more than 1h after receipt',
)
# Counted from the DB, not from the per-process webhook counter: one event
# must be enough to alert, and the API's gunicorn workers each keep their
# own counter (MAP-231).
webhook_events_failed_15m = Gauge(
    'maplekey_webhook_events_failed_15m',
    'Helcim webhook events that landed in an alert state in the last 15 min',
)
scheduler_last_tick_timestamp = Gauge(
    'maplekey_scheduler_last_tick_timestamp',
    'Unix time of the last scheduler tick',
)


class Command(BaseCommand):
    help = 'Run retry_webhook_events every 15 min and sync_helcim_payments daily; export the webhook gauges.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once', action='store_true',
            help='Run a single tick and exit (tests/cron); no metrics server.',
        )

    def handle(self, *args, **options):
        # An Event, not a flag: time.sleep() resumes after a signal handler
        # returns, so a bare flag was only noticed up to 60 s later and docker
        # stop (10 s default grace) SIGKILLed the container (MAP-215).
        # Event.wait() returns the moment _request_stop sets it.
        self._stop_event = threading.Event()
        signal.signal(signal.SIGTERM, self._request_stop)
        signal.signal(signal.SIGINT, self._request_stop)
        self._next_retry_at = None   # None → due now
        self._last_sync_day = None

        if not options['once']:
            start_http_server(int(os.environ.get('SCHEDULER_METRICS_PORT', '9103')))
        logger.info('Scheduler started (once=%s)', options['once'])

        while not self._stop_event.is_set():
            self._tick()
            if options['once']:
                break
            self._stop_event.wait(TICK_SLEEP_SECONDS)

        logger.info('Scheduler stopped')

    def _request_stop(self, signum, frame):
        logger.info('Scheduler received signal %s — stopping after current tick', signum)
        self._stop_event.set()

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
        webhook_events_failed_15m.set(HelcimWebhookEvent.objects.filter(
            processing_status__in=ALERT_STATES,
            processed_at__gte=now - ALERT_WINDOW,
        ).count())
        scheduler_last_tick_timestamp.set(now.timestamp())
        if unresolved:
            logger.warning('%s webhook event(s) unresolved for more than 1h', unresolved)
