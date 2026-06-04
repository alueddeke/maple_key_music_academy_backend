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
  - School FK never defaulted to first() — stays None until Phase 20 (multi-school constraint).
  - Signature value is never logged (T-18-C5).
  - Phase 20 (D-03): inline credit application after event.save() — wrapped in
    transaction.atomic() with select_for_update() on StudentCreditAccount.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import hmac
import hashlib
import base64
import json
import logging
from decimal import Decimal
from django.conf import settings
from ..models import HelcimWebhookEvent, PreBillingInvoice, StudentCreditAccount, CreditTransaction
from ..services.helcim_client import HelcimClient, HelcimAPIError

logger = logging.getLogger(__name__)


def verify_helcim_signature(
    raw_body: bytes,
    webhook_id: str,
    webhook_timestamp: str,
    webhook_signature: str,
) -> bool:
    """
    Verify Helcim SVix-style HMAC-SHA256 webhook signature.

    Signed content: "{webhook_id}.{webhook_timestamp}.{raw_body_string}"
    Key: base64-decoded HELCIM_WEBHOOK_SECRET (env var is base64-encoded).
    Expected: base64-encoded HMAC-SHA256 digest.
    Comparison: hmac.compare_digest() — timing-safe.

    Empty webhook_signature goes through compare_digest; no early return on
    empty string (that would create a timing oracle).
    """
    signed_content = f"{webhook_id}.{webhook_timestamp}.{raw_body.decode('utf-8')}"
    # T-18-C10: base64-decode the env var before use as HMAC key (Pitfall 5)
    secret_bytes = base64.b64decode(settings.HELCIM_WEBHOOK_SECRET)
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content.encode('utf-8'), hashlib.sha256).digest()
    ).decode('utf-8')
    return hmac.compare_digest(expected, webhook_signature)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def payment_callback(request):
    """
    POST /api/billing/payment-callback/

    Receives Helcim cardTransaction webhook, verifies HMAC signature, deduplicates
    via get_or_create, then performs a secondary GET to retrieve invoiceNumber + amount
    (the webhook payload only contains id + type per D-13).

    Returns:
        200 {"status": "ok"}        — new event stored with invoiceNumber + amount.
        200 {"status": "duplicate"} — event already recorded (idempotent retry).
        403 {"error": "Invalid signature"} — HMAC mismatch.
        400 {"error": ...}          — malformed body or missing transaction id.

    school FK is None at receipt — Phase 20 sets it during credit reconciliation.
    """
    # Pitfall 3: raw bytes read as first statement — must come before any field parsing.
    raw_body = request.body

    webhook_id = request.headers.get('webhook-id', '')
    webhook_timestamp = request.headers.get('webhook-timestamp', '')
    webhook_signature = request.headers.get('webhook-signature', '')

    if not verify_helcim_signature(raw_body, webhook_id, webhook_timestamp, webhook_signature):
        # T-18-C5: log webhook-id only, never the signature value or secret.
        logger.warning('Helcim webhook HMAC verification failed for webhook-id=%s', webhook_id)
        return Response({'error': 'Invalid signature'}, status=403)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return Response({'error': 'Invalid JSON'}, status=400)

    tx_id = str(payload.get('id', ''))
    if not tx_id:
        return Response({'error': 'Missing transaction id'}, status=400)

    # D-12 / HELM-04: idempotency guard via unique constraint on helcim_transaction_id.
    # school=None: no school context from unauthenticated webhook (Phase 20 sets it).
    event, created = HelcimWebhookEvent.objects.get_or_create(
        helcim_transaction_id=tx_id,
        defaults={
            'raw_payload': payload,
            'invoice_id': '',
            'amount': Decimal('0.00'),
            'school': None,
        },
    )
    if not created:
        return Response({'status': 'duplicate'}, status=200)

    # D-13: secondary GET — webhook payload is minimal ({id, type} only); invoiceNumber
    # and amount require a separate card-transactions API call.
    # NOT wrapped in any DB transaction — HTTP calls outside DB is the project pattern.
    client = HelcimClient()
    try:
        tx_details = client.get_card_transaction(tx_id)
        invoice_number = str(tx_details.get('invoiceNumber', ''))
        # T-18-C7: Decimal(str(...)) — never float() for money (CONVENTIONS.md)
        amount = Decimal(str(tx_details.get('amount', '0')))
    except HelcimAPIError as e:
        logger.error(
            'Helcim secondary GET failed for transaction %s: %s',
            tx_id,
            str(e),
        )
        # Preserve row with blank invoice_id and 0.00 — Phase 20 can retry.
        invoice_number = ''
        amount = Decimal('0.00')

    event.invoice_id = invoice_number
    event.amount = amount
    event.save()

    # Phase 20 (D-03, D-04, D-05): inline credit application — DB-only, safe inside atomic.
    # Guard: skip if invoice_id is blank or amount is 0.00 (Pitfall 1 — CreditTransaction
    # has a DB CHECK amount__gt=0 that would raise IntegrityError on zero-amount write).
    if event.invoice_id and event.amount > Decimal('0.00'):
        try:
            with transaction.atomic():
                # Use filter().order_by('-id').first() instead of .get() to guard against
                # MultipleObjectsReturned — helcim_invoice_id has no unique constraint on
                # the model, so a duplicate ID would crash the webhook with 500 and cause
                # Helcim to retry indefinitely. None is handled identically to DoesNotExist.
                invoice = (
                    PreBillingInvoice.objects
                    .filter(helcim_invoice_id=event.invoice_id)
                    .order_by('-id')
                    .first()
                )
                if invoice is None:
                    logger.warning(
                        'Phase 20: credit not applied for webhook event %s — '
                        'no PreBillingInvoice found for invoice_id=%s',
                        event.helcim_transaction_id,
                        event.invoice_id,
                    )
                    # Return without raising so the outer try/except stays clean;
                    # transaction.atomic() exits normally with no writes.
                else:
                    account = StudentCreditAccount.objects.select_for_update().get(
                        student=invoice.student,
                        school=invoice.school,
                    )
                    CreditTransaction.objects.create(
                        account=account,
                        school=invoice.school,
                        type='pre_billing_payment',
                        amount=event.amount,
                    )
                    account.balance += event.amount
                    account.save()
                    event.school = invoice.school
                    event.save(update_fields=['school'])
                    invoice.status = 'paid'
                    invoice.save(update_fields=['status', 'updated_at'])
        except StudentCreditAccount.DoesNotExist as exc:
            logger.warning(
                'Phase 20: credit not applied for webhook event %s — %s',
                event.helcim_transaction_id,
                exc,
            )

    return Response({'status': 'ok'}, status=200)
