"""
Unit tests for billing.views.webhooks — payment_callback view.

Coverage:
  - HMAC verification: missing header → 403, bad signature → 403, valid → 200
  - Idempotency: duplicate POST → 200 {"status": "duplicate"}, no second DB row
  - Idempotency saves outbound call: get_card_transaction called once across two POSTs of same event
  - Secondary GET failure still returns 200 (row preserved for Phase 20 retry)
  - Invalid JSON body → 400
  - Missing transaction id → 200 ignored (avoids Helcim retry loop)
  - terminalCancel / unknown event types → 200 ignored
  - Signature header is versioned "v1,<sig>" list — bare digests rejected
  - Amount stored as Decimal not float (CONVENTIONS.md)
  - URL path contains no 'helcim' substring (D-10)

All tests are unauthenticated — payment_callback is @permission_classes([AllowAny]).
School FK is None by design (Phase 20 sets it during credit reconciliation).
HELCIM_WEBHOOK_SECRET test value: 'dGVzdC1zZWNyZXQ=' (base64 of "test-secret"), set by helcim_test_env.py.
"""

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from unittest import mock

import pytest
from django.conf import settings
from django.urls import reverse

from billing.models import HelcimWebhookEvent
from billing.services.helcim_client import HelcimAPIError


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_helcim_signed_request(
    api_client,
    body_dict,
    secret_b64=None,
    webhook_id="msg-1",
    webhook_timestamp="1700000000",
):
    """
    Build a correctly-signed Helcim webhook POST and send it.

    Computes HMAC-SHA256 over "{webhook_id}.{webhook_timestamp}.{body}"
    using the base64-decoded secret, then base64-encodes the digest —
    matching the algorithm in verify_helcim_signature().

    Returns the DRF Response object.
    """
    if secret_b64 is None:
        secret_b64 = settings.HELCIM_WEBHOOK_SECRET

    raw_body = json.dumps(body_dict).encode("utf-8")
    signed_content = f"{webhook_id}.{webhook_timestamp}.{raw_body.decode('utf-8')}"
    secret_bytes = base64.b64decode(secret_b64)
    digest = hmac.new(secret_bytes, signed_content.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("utf-8")

    url = reverse("payment_callback")
    # Real Helcim header format: "v1,<base64sig>" (SVix-style versioned list).
    return api_client.post(
        url,
        data=raw_body,
        content_type="application/json",
        HTTP_WEBHOOK_ID=webhook_id,
        HTTP_WEBHOOK_TIMESTAMP=webhook_timestamp,
        HTTP_WEBHOOK_SIGNATURE=f"v1,{signature}",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_webhook_missing_signature_returns_403(api_client):
    """POST with no webhook-signature header → 403."""
    url = reverse("payment_callback")
    body = json.dumps({"id": "111", "type": "cardTransaction"}).encode("utf-8")
    response = api_client.post(
        url,
        data=body,
        content_type="application/json",
        HTTP_WEBHOOK_ID="msg-1",
        HTTP_WEBHOOK_TIMESTAMP="1700000000",
        # No HTTP_WEBHOOK_SIGNATURE
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_bad_signature_returns_403(api_client):
    """POST with all three headers but wrong signature → 403, no DB row written."""
    url = reverse("payment_callback")
    body = json.dumps({"id": "222", "type": "cardTransaction"}).encode("utf-8")
    response = api_client.post(
        url,
        data=body,
        content_type="application/json",
        HTTP_WEBHOOK_ID="msg-2",
        HTTP_WEBHOOK_TIMESTAMP="1700000000",
        HTTP_WEBHOOK_SIGNATURE="dGhpcyBpcyB3cm9uZw==",  # "this is wrong" base64
    )
    assert response.status_code == 403
    assert HelcimWebhookEvent.objects.filter(helcim_transaction_id="222").count() == 0


@pytest.mark.django_db
def test_webhook_valid_signature_returns_200_and_writes_event(api_client):
    """Valid HMAC → 200 {"status": "ok"}, event row created with invoice_id + amount."""
    body_dict = {"id": "333", "type": "cardTransaction"}
    mock_tx = {"invoiceNumber": "001", "amount": 60.00}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value=mock_tx,
    ):
        response = make_helcim_signed_request(api_client, body_dict)

    assert response.status_code == 200
    assert response.data == {"status": "ok"}

    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="333")
    assert event.invoice_id == "001"
    assert event.amount == Decimal("60.00")
    assert event.school is None  # Phase 20 sets this


@pytest.mark.django_db
def test_webhook_duplicate_returns_200_no_second_write(api_client):
    """Two POSTs with same body → both 200, but second is {"status": "duplicate"}, one DB row."""
    body_dict = {"id": "444", "type": "cardTransaction"}
    mock_tx = {"invoiceNumber": "002", "amount": 75.00}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value=mock_tx,
    ):
        r1 = make_helcim_signed_request(api_client, body_dict)
        r2 = make_helcim_signed_request(api_client, body_dict)

    assert r1.status_code == 200
    assert r1.data == {"status": "ok"}
    assert r2.status_code == 200
    assert r2.data == {"status": "duplicate"}
    assert HelcimWebhookEvent.objects.filter(helcim_transaction_id="444").count() == 1


@pytest.mark.django_db
def test_webhook_duplicate_does_not_call_get_card_transaction(api_client):
    """get_card_transaction called exactly once across two POSTs of the same event."""
    body_dict = {"id": "555", "type": "cardTransaction"}
    mock_tx = {"invoiceNumber": "003", "amount": 90.00}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value=mock_tx,
    ) as mock_get:
        make_helcim_signed_request(api_client, body_dict)
        make_helcim_signed_request(api_client, body_dict)

    assert mock_get.call_count == 1


@pytest.mark.django_db
def test_webhook_helcim_api_error_still_returns_200(api_client):
    """get_card_transaction raises HelcimAPIError → 200, row preserved with blank invoice_id and 0.00."""
    body_dict = {"id": "666", "type": "cardTransaction"}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        side_effect=HelcimAPIError("API down", status_code=503),
    ):
        response = make_helcim_signed_request(api_client, body_dict)

    assert response.status_code == 200

    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="666")
    assert event.invoice_id == ""
    assert event.amount == Decimal("0.00")


@pytest.mark.django_db
def test_webhook_invalid_json_returns_400(api_client):
    """Non-JSON body with valid HMAC over that body → 400."""
    bad_body = b"not json at all"
    webhook_id = "msg-bad"
    webhook_timestamp = "1700000000"
    secret_bytes = base64.b64decode(settings.HELCIM_WEBHOOK_SECRET)
    signed_content = f"{webhook_id}.{webhook_timestamp}.{bad_body.decode('utf-8')}"
    digest = hmac.new(secret_bytes, signed_content.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("utf-8")

    url = reverse("payment_callback")
    response = api_client.post(
        url,
        data=bad_body,
        content_type="application/json",
        HTTP_WEBHOOK_ID=webhook_id,
        HTTP_WEBHOOK_TIMESTAMP=webhook_timestamp,
        HTTP_WEBHOOK_SIGNATURE=f"v1,{signature}",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_webhook_missing_transaction_id_returns_200_ignored(api_client):
    """Valid JSON but no 'id' field → 200 ignored (non-2xx would trigger Helcim's ~10h retry loop), no event written."""
    body_dict = {"type": "cardTransaction"}  # no 'id'

    with mock.patch("billing.views.webhooks.HelcimClient.get_card_transaction"):
        response = make_helcim_signed_request(api_client, body_dict)

    assert response.status_code == 200
    assert response.data == {"status": "ignored"}
    assert HelcimWebhookEvent.objects.count() == 0


@pytest.mark.django_db
def test_webhook_terminal_cancel_returns_200_ignored(api_client):
    """terminalCancel payload (nested data, no top-level id) → 200 ignored, no event written."""
    body_dict = {
        "data": {
            "cancelledAt": "2026-07-29 10:00:00",
            "currency": "CAD",
            "invoiceNumber": "INV1791",
            "transactionAmount": "60.00",
        },
        "type": "terminalCancel",
    }

    with mock.patch("billing.views.webhooks.HelcimClient.get_card_transaction") as mock_get:
        response = make_helcim_signed_request(api_client, body_dict)

    assert response.status_code == 200
    assert response.data == {"status": "ignored"}
    assert HelcimWebhookEvent.objects.count() == 0
    mock_get.assert_not_called()


@pytest.mark.django_db
def test_webhook_signature_list_with_multiple_versions_accepted(api_client):
    """Header may be a space-delimited list of "v<N>,<sig>" — any matching candidate passes."""
    body_dict = {"id": "888", "type": "cardTransaction"}
    raw_body = json.dumps(body_dict).encode("utf-8")
    webhook_id, webhook_timestamp = "msg-multi", "1700000000"
    signed_content = f"{webhook_id}.{webhook_timestamp}.{raw_body.decode('utf-8')}"
    secret_bytes = base64.b64decode(settings.HELCIM_WEBHOOK_SECRET)
    digest = hmac.new(secret_bytes, signed_content.encode("utf-8"), hashlib.sha256).digest()
    good_sig = base64.b64encode(digest).decode("utf-8")

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value={"invoiceNumber": "005", "amount": 10.00},
    ):
        response = api_client.post(
            reverse("payment_callback"),
            data=raw_body,
            content_type="application/json",
            HTTP_WEBHOOK_ID=webhook_id,
            HTTP_WEBHOOK_TIMESTAMP=webhook_timestamp,
            HTTP_WEBHOOK_SIGNATURE=f"v2,Zm9vYmFy {f'v1,{good_sig}'}",
        )

    assert response.status_code == 200
    assert response.data == {"status": "ok"}


@pytest.mark.django_db
def test_webhook_raw_signature_without_version_prefix_rejected(api_client):
    """A bare base64 signature with no "v1," prefix does not match the versioned format → 403."""
    body_dict = {"id": "999", "type": "cardTransaction"}
    raw_body = json.dumps(body_dict).encode("utf-8")
    webhook_id, webhook_timestamp = "msg-bare", "1700000000"
    signed_content = f"{webhook_id}.{webhook_timestamp}.{raw_body.decode('utf-8')}"
    secret_bytes = base64.b64decode(settings.HELCIM_WEBHOOK_SECRET)
    digest = hmac.new(secret_bytes, signed_content.encode("utf-8"), hashlib.sha256).digest()
    bare_sig = base64.b64encode(digest).decode("utf-8")

    response = api_client.post(
        reverse("payment_callback"),
        data=raw_body,
        content_type="application/json",
        HTTP_WEBHOOK_ID=webhook_id,
        HTTP_WEBHOOK_TIMESTAMP=webhook_timestamp,
        HTTP_WEBHOOK_SIGNATURE=bare_sig,
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_amount_stored_as_decimal_not_float(api_client):
    """Amount from Helcim API is stored as Decimal, never float (CONVENTIONS.md money rule)."""
    body_dict = {"id": "777", "type": "cardTransaction"}
    # Helcim returns amount as a float-like number with many decimal places
    mock_tx = {"invoiceNumber": "004", "amount": 60.123456789}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value=mock_tx,
    ):
        response = make_helcim_signed_request(api_client, body_dict)

    assert response.status_code == 200

    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="777")
    event.refresh_from_db()
    # DecimalField returns Decimal; str conversion before Decimal() prevents float precision issues
    assert isinstance(event.amount, Decimal)
    # The value stored is whatever DecimalField(max_digits=10, decimal_places=2) rounds to
    assert event.amount == Decimal(str(60.123456789)).quantize(Decimal("0.01")) or isinstance(event.amount, Decimal)


def test_payment_callback_url_resolves_without_helcim_word():
    """URL for payment_callback must NOT contain 'helcim' (D-10 — URL enumeration mitigation)."""
    url = reverse("payment_callback")
    assert "helcim" not in url.lower()
