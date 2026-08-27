"""
Unit tests for webhook credit gating + recovery (billing/services/webhook_processing.py).

Money-safety coverage the original webhook tests lacked:
  - DECLINED transaction → recorded, NO credit, invoice untouched
  - refund/reverse transaction type → recorded, NO credit (manual review)
  - Partial payment → wallet credited with the real amount, invoice stays open,
    event flagged credited_partial; a second payment covering the rest flips paid
  - Enrichment failure recovery: event stuck enrichment_failed is re-processed
    on Helcim redelivery (duplicate POST) and by the retry_webhook_events command
  - Terminal states are never re-processed (no double credit on redelivery)
"""

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse

from billing.models import (
    HelcimWebhookEvent,
    PreBillingInvoice,
    StudentCreditAccount,
    CreditTransaction,
)
from billing.services.helcim_client import HelcimAPIError
from billing.services.webhook_processing import process_webhook_event

PATCH_TARGET = "billing.services.webhook_processing.HelcimClient.get_card_transaction"


def make_helcim_signed_request(api_client, body_dict, webhook_id="msg-1"):
    """Signed webhook POST — same algorithm as verify_helcim_signature()."""
    raw_body = json.dumps(body_dict).encode("utf-8")
    signed_content = f"{webhook_id}.1700000000.{raw_body.decode('utf-8')}"
    secret_bytes = base64.b64decode(settings.HELCIM_WEBHOOK_SECRET)
    digest = hmac.new(secret_bytes, signed_content.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("utf-8")
    return api_client.post(
        reverse("payment_callback"),
        data=raw_body,
        content_type="application/json",
        HTTP_WEBHOOK_ID=webhook_id,
        HTTP_WEBHOOK_TIMESTAMP="1700000000",
        HTTP_WEBHOOK_SIGNATURE=f"v1,{signature}",
    )


def _invoice_and_account(school, student_user, number, amount="60.00"):
    invoice = PreBillingInvoice.objects.create(
        student=student_user,
        school=school,
        status="sent",
        amount=Decimal(amount),
        period_start="2026-08-01",
        period_end="2026-08-31",
        helcim_invoice_number=number,
    )
    account = StudentCreditAccount.objects.create(
        student=student_user, school=school, balance=Decimal("0.00")
    )
    return invoice, account


@pytest.mark.django_db
def test_declined_transaction_never_credits(api_client, school, student_user):
    """DECLINED payment attempt → event recorded not_approved, wallet + invoice untouched."""
    invoice, account = _invoice_and_account(school, student_user, "INV-GATE-1")
    mock_tx = {"invoiceNumber": "INV-GATE-1", "amount": "60.00",
               "status": "DECLINED", "type": "purchase"}

    with mock.patch(PATCH_TARGET, return_value=mock_tx):
        response = make_helcim_signed_request(
            api_client, {"id": "tx-declined-1", "type": "cardTransaction"}, "msg-d1"
        )

    assert response.status_code == 200
    assert CreditTransaction.objects.count() == 0
    account.refresh_from_db()
    assert account.balance == Decimal("0.00")
    invoice.refresh_from_db()
    assert invoice.status == "sent"
    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="tx-declined-1")
    assert event.processing_status == "not_approved"


@pytest.mark.django_db
def test_refund_transaction_never_credits(api_client, school, student_user):
    """Refund issued from the Helcim dashboard must NOT add wallet credit."""
    invoice, account = _invoice_and_account(school, student_user, "INV-GATE-2")
    mock_tx = {"invoiceNumber": "INV-GATE-2", "amount": "60.00",
               "status": "APPROVED", "type": "refund"}

    with mock.patch(PATCH_TARGET, return_value=mock_tx):
        make_helcim_signed_request(
            api_client, {"id": "tx-refund-1", "type": "cardTransaction"}, "msg-r1"
        )

    assert CreditTransaction.objects.count() == 0
    account.refresh_from_db()
    assert account.balance == Decimal("0.00")
    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="tx-refund-1")
    assert event.processing_status == "non_purchase"


@pytest.mark.django_db
def test_partial_payment_credits_wallet_but_leaves_invoice_open(api_client, school, student_user):
    """Short payment: wallet gets the real money, invoice must NOT flip paid."""
    invoice, account = _invoice_and_account(school, student_user, "INV-GATE-3", "100.00")
    mock_tx = {"invoiceNumber": "INV-GATE-3", "amount": "40.00",
               "status": "APPROVED", "type": "purchase"}

    with mock.patch(PATCH_TARGET, return_value=mock_tx):
        make_helcim_signed_request(
            api_client, {"id": "tx-partial-1", "type": "cardTransaction"}, "msg-p1"
        )

    account.refresh_from_db()
    assert account.balance == Decimal("40.00")
    invoice.refresh_from_db()
    assert invoice.status == "sent"
    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="tx-partial-1")
    assert event.processing_status == "credited_partial"


@pytest.mark.django_db
def test_second_partial_payment_covers_invoice(api_client, school, student_user):
    """Coverage is cumulative: 40 + 60 on a 100 invoice → invoice paid on the second event."""
    invoice, account = _invoice_and_account(school, student_user, "INV-GATE-4", "100.00")

    with mock.patch(PATCH_TARGET, return_value={
        "invoiceNumber": "INV-GATE-4", "amount": "40.00",
        "status": "APPROVED", "type": "purchase",
    }):
        make_helcim_signed_request(
            api_client, {"id": "tx-cum-1", "type": "cardTransaction"}, "msg-c1"
        )
    with mock.patch(PATCH_TARGET, return_value={
        "invoiceNumber": "INV-GATE-4", "amount": "60.00",
        "status": "APPROVED", "type": "purchase",
    }):
        make_helcim_signed_request(
            api_client, {"id": "tx-cum-2", "type": "cardTransaction"}, "msg-c2"
        )

    account.refresh_from_db()
    assert account.balance == Decimal("100.00")
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    assert HelcimWebhookEvent.objects.get(
        helcim_transaction_id="tx-cum-2"
    ).processing_status == "credited"


@pytest.mark.django_db
def test_redelivery_recovers_enrichment_failure(api_client, school, student_user):
    """First delivery: secondary GET down → enrichment_failed. Redelivery: enriches + credits."""
    invoice, account = _invoice_and_account(school, student_user, "INV-GATE-5")
    body = {"id": "tx-recover-1", "type": "cardTransaction"}

    with mock.patch(PATCH_TARGET, side_effect=HelcimAPIError("API down", status_code=503)):
        make_helcim_signed_request(api_client, body, "msg-rec1")

    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="tx-recover-1")
    assert event.processing_status == "enrichment_failed"
    assert CreditTransaction.objects.count() == 0

    with mock.patch(PATCH_TARGET, return_value={
        "invoiceNumber": "INV-GATE-5", "amount": "60.00",
        "status": "APPROVED", "type": "purchase",
    }):
        response = make_helcim_signed_request(api_client, body, "msg-rec1")

    assert response.status_code == 200
    event.refresh_from_db()
    assert event.processing_status == "credited"
    account.refresh_from_db()
    assert account.balance == Decimal("60.00")
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    assert HelcimWebhookEvent.objects.count() == 1


@pytest.mark.django_db
def test_redelivery_of_credited_event_never_double_credits(api_client, school, student_user):
    """Terminal 'credited' events are not re-processed on redelivery."""
    invoice, account = _invoice_and_account(school, student_user, "INV-GATE-6")
    body = {"id": "tx-once-1", "type": "cardTransaction"}
    mock_tx = {"invoiceNumber": "INV-GATE-6", "amount": "60.00",
               "status": "APPROVED", "type": "purchase"}

    with mock.patch(PATCH_TARGET, return_value=mock_tx) as mock_get:
        make_helcim_signed_request(api_client, body, "msg-o1")
        r2 = make_helcim_signed_request(api_client, body, "msg-o1")

    assert r2.data == {"status": "duplicate"}
    assert mock_get.call_count == 1
    assert CreditTransaction.objects.count() == 1
    account.refresh_from_db()
    assert account.balance == Decimal("60.00")


@pytest.mark.django_db
def test_retry_command_recovers_stuck_event(school, student_user):
    """retry_webhook_events re-enriches and credits a stuck event."""
    invoice, account = _invoice_and_account(school, student_user, "INV-GATE-7")
    event = HelcimWebhookEvent.objects.create(
        helcim_transaction_id="tx-cmd-1",
        raw_payload={"id": "tx-cmd-1", "type": "cardTransaction"},
        invoice_id="",
        amount=Decimal("0.00"),
        processing_status="enrichment_failed",
    )

    out = StringIO()
    with mock.patch(PATCH_TARGET, return_value={
        "invoiceNumber": "INV-GATE-7", "amount": "60.00",
        "status": "APPROVED", "type": "purchase",
    }):
        call_command("retry_webhook_events", stdout=out)

    event.refresh_from_db()
    assert event.processing_status == "credited"
    account.refresh_from_db()
    assert account.balance == Decimal("60.00")
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    assert "credited" in out.getvalue()


@pytest.mark.django_db
def test_retry_command_dry_run_changes_nothing(school, student_user):
    """--dry-run lists retryable events without touching them."""
    HelcimWebhookEvent.objects.create(
        helcim_transaction_id="tx-cmd-2",
        raw_payload={"id": "tx-cmd-2", "type": "cardTransaction"},
        invoice_id="",
        amount=Decimal("0.00"),
        processing_status="enrichment_failed",
    )

    out = StringIO()
    with mock.patch(PATCH_TARGET) as mock_get:
        call_command("retry_webhook_events", "--dry-run", stdout=out)

    mock_get.assert_not_called()
    assert HelcimWebhookEvent.objects.get(
        helcim_transaction_id="tx-cmd-2"
    ).processing_status == "enrichment_failed"


@pytest.mark.django_db
def test_process_event_direct_no_invoice_is_retryable_then_recovers(school, student_user):
    """no_invoice state: webhook raced ahead of invoice creation, retry after the fact succeeds."""
    event = HelcimWebhookEvent.objects.create(
        helcim_transaction_id="tx-race-1",
        raw_payload={"id": "tx-race-1", "type": "cardTransaction"},
        invoice_id="INV-GATE-8",
        amount=Decimal("60.00"),
        transaction_status="APPROVED",
        transaction_type="purchase",
        processing_status="no_invoice",
    )
    invoice, account = _invoice_and_account(school, student_user, "INV-GATE-8")

    process_webhook_event(event)

    event.refresh_from_db()
    assert event.processing_status == "credited"
    account.refresh_from_db()
    assert account.balance == Decimal("60.00")
