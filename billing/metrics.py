"""
Business metrics for the money path (observability wave, Aug 28 audit).

django-prometheus exposes these on /metrics alongside the request metrics.
Generic server metrics say the box is healthy; these say money is moving:
a webhook outcome counter that never increments 'credited' while invoices
are outstanding is the alert that matters.
"""
from prometheus_client import Counter

# Webhook reconciliation outcomes. Labels mirror processing_status terminal/
# retryable states: credited, credited_partial, enrichment_failed, no_invoice,
# no_account, ignored_type, ...
webhook_events_total = Counter(
    'maplekey_webhook_events_total',
    'Helcim webhook events by reconciliation outcome',
    ['outcome'],
)

# Invoice sends through Helcim. result: sent | failed
invoices_sent_total = Counter(
    'maplekey_invoices_sent_total',
    'Pre-billing invoices sent via Helcim',
    ['result'],
)
