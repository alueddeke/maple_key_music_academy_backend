"""
billing/views/webhooks.py — Helcim payment webhook receiver.

HELM-03: POST /api/billing/payment-callback/ (no 'helcim' in path per D-10).
HELM-04: Idempotency via get_or_create on helcim_transaction_id.

Security constraints enforced:
  - HMAC-SHA256 over "{webhook-id}.{webhook-timestamp}.{body}" with base64-decoded secret.
  - hmac.compare_digest() for timing-safe comparison (never ==).
  - Raw body bytes read as FIRST statement before any field parsing (Pitfall 3).
  - No DB transactions around HTTP calls (STATE.md architectural constraint).
  - Money amounts stored via Decimal(str(value)), never via float casting (CONVENTIONS.md).
  - Signature value is never logged (T-18-C5).
  - Signature is verified against the env HELCIM_WEBHOOK_SECRET and every
    School with its own helcim_webhook_secret; a per-school match pins the
    event's school so enrichment uses that school's API token (multi-school).

Credit reconciliation lives in billing/services/webhook_processing.py —
shared with the retry_webhook_events command and the admin retry action.
Credit is gated on status=APPROVED + type=purchase/capture there; declines
and refunds are recorded but never increase a wallet.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
import hmac
import hashlib
import base64
import json
import logging
from decimal import Decimal
from django.conf import settings
from ..models import HelcimWebhookEvent, School
from ..services.webhook_processing import process_webhook_event, RETRYABLE_STATES

logger = logging.getLogger(__name__)


def _signature_matches(secret_b64, raw_body, webhook_id, webhook_timestamp, webhook_signature):
    """
    Check one SVix-style HMAC-SHA256 signature against one base64 secret.

    Signed content: "{webhook_id}.{webhook_timestamp}.{raw_body_string}"
    Header format: space-delimited "v<N>,<base64sig>" entries — the version
    prefix must be stripped before comparison; comparing the raw header value
    fails 100% of the time.

    Empty webhook_signature still goes through compare_digest; no early
    return on empty string (that would create a timing oracle).
    """
    signed_content = f"{webhook_id}.{webhook_timestamp}.{raw_body.decode('utf-8')}"
    try:
        # T-18-C10: base64-decode the secret before use as HMAC key (Pitfall 5)
        secret_bytes = base64.b64decode(secret_b64)
    except Exception:
        return False
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content.encode('utf-8'), hashlib.sha256).digest()
    ).decode('utf-8')
    for candidate in webhook_signature.split(' '):
        _version, _sep, signature = candidate.partition(',')
        if hmac.compare_digest(expected, signature):
            return True
    return False


def verify_helcim_signature(raw_body, webhook_id, webhook_timestamp, webhook_signature):
    """
    Verify the webhook signature against all known verifier tokens.

    Returns (verified: bool, school: School | None). school is set when a
    school-specific secret matched — the event is then pinned to that school
    so enrichment uses its API token. The env secret matches with school=None
    (default/first school).
    """
    if settings.HELCIM_WEBHOOK_SECRET and _signature_matches(
        settings.HELCIM_WEBHOOK_SECRET, raw_body, webhook_id, webhook_timestamp, webhook_signature
    ):
        return True, None
    for school in School.objects.exclude(helcim_webhook_secret=''):
        if _signature_matches(
            school.helcim_webhook_secret, raw_body, webhook_id, webhook_timestamp, webhook_signature
        ):
            return True, school
    return False, None


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def payment_callback(request):
    """
    POST /api/billing/payment-callback/

    Receives Helcim cardTransaction webhook, verifies HMAC signature,
    deduplicates via get_or_create, then hands off to process_webhook_event
    for enrichment (secondary GET) + gated credit application.

    Returns:
        200 {"status": "ok"}        — event stored/processed.
        200 {"status": "duplicate"} — event already in a terminal state.
        200 {"status": "ignored"}   — non-cardTransaction or id-less payload
                                      (non-2xx would trigger ~10h of retries).
        403 {"error": "Invalid signature"} — HMAC mismatch on every secret.
        400 {"error": ...}          — malformed JSON body.

    Helcim redelivers on non-2xx AND on its own retry schedule — a duplicate
    whose prior processing landed in a retryable state (enrichment_failed,
    no_invoice, no_account) is re-processed here instead of being dropped,
    so a transient API failure self-heals on the next redelivery.
    """
    # Pitfall 3: raw bytes read as first statement — must come before any field parsing.
    raw_body = request.body

    webhook_id = request.headers.get('webhook-id', '')
    webhook_timestamp = request.headers.get('webhook-timestamp', '')
    webhook_signature = request.headers.get('webhook-signature', '')

    verified, matched_school = verify_helcim_signature(
        raw_body, webhook_id, webhook_timestamp, webhook_signature
    )
    if not verified:
        # T-18-C5: log webhook-id only, never the signature value or secret.
        logger.warning('Helcim webhook HMAC verification failed for webhook-id=%s', webhook_id)
        return Response({'error': 'Invalid signature'}, status=403)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return Response({'error': 'Invalid JSON'}, status=400)

    # Non-cardTransaction events (e.g. terminalCancel — nested {data, type},
    # no top-level id) must be acknowledged with 200: Helcim retries any
    # non-2xx on a backoff schedule up to ~10h, so a 400 here becomes a
    # retry loop hammering the endpoint.
    event_type = str(payload.get('type', ''))
    if event_type != 'cardTransaction':
        logger.info('Ignoring Helcim webhook type=%s', event_type)
        return Response({'status': 'ignored'}, status=200)

    tx_id = str(payload.get('id', ''))
    if not tx_id:
        # Same payload gets retried verbatim — a 400 can never succeed later.
        logger.warning('Helcim cardTransaction webhook missing id — ignoring')
        return Response({'status': 'ignored'}, status=200)

    # D-12 / HELM-04: idempotency guard via unique constraint on helcim_transaction_id.
    # school is the signature-matched school (None for the env/default secret);
    # process_webhook_event overwrites it with the invoice's school on credit.
    event, created = HelcimWebhookEvent.objects.get_or_create(
        helcim_transaction_id=tx_id,
        defaults={
            'raw_payload': payload,
            'invoice_id': '',
            'amount': Decimal('0.00'),
            'school': matched_school,
        },
    )
    if not created and event.processing_status not in RETRYABLE_STATES:
        return Response({'status': 'duplicate'}, status=200)

    process_webhook_event(event)
    return Response({'status': 'ok' if created else 'duplicate'}, status=200)
