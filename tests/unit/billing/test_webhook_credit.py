"""
Unit tests for Phase 20 webhook credit application.

Coverage:
  - Happy path: valid webhook + matching PreBillingInvoice → CreditTransaction created,
    balance incremented, invoice.status='paid', event.school set
  - Unresolved invoice_id (DoesNotExist) → warning logged, 200 returned, no CreditTransaction
  - Missing StudentCreditAccount (DoesNotExist) → warning logged, 200 returned, no credit
  - Zero-amount event (secondary GET failed) → credit block skipped (Pitfall 1 guard)
  - Blank invoice_id → credit block skipped
  - Idempotency: duplicate POST → no second CreditTransaction (idempotency guard holds)

Tests are RED until Plan 03 implements the credit application block in payment_callback.
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

from billing.models import (
    HelcimWebhookEvent,
    PreBillingInvoice,
    StudentCreditAccount,
    CreditTransaction,
)
from billing.services.helcim_client import HelcimAPIError


# ---------------------------------------------------------------------------
# Helper — copied verbatim from tests/unit/billing/test_webhook.py
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
    return api_client.post(
        url,
        data=raw_body,
        content_type="application/json",
        HTTP_WEBHOOK_ID=webhook_id,
        HTTP_WEBHOOK_TIMESTAMP=webhook_timestamp,
        HTTP_WEBHOOK_SIGNATURE=signature,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_webhook_credit_happy_path_creates_credit_transaction_and_increments_balance(
    api_client, school, student_user
):
    """
    Valid webhook + matching PreBillingInvoice + existing StudentCreditAccount
    → CreditTransaction(type='pre_billing_payment') created, balance incremented,
    invoice.status='paid', event.school set.

    RED until Plan 03 implements the credit resolution block in payment_callback.
    """
    # Create PreBillingInvoice with a known helcim_invoice_id
    invoice = PreBillingInvoice.objects.create(
        student=student_user,
        school=school,
        status='sent',
        amount=Decimal('60.00'),
        period_start='2026-06-01',
        period_end='2026-06-30',
        helcim_invoice_id='INV-2026-06-S1-0001',
    )

    # Create StudentCreditAccount with zero balance
    account = StudentCreditAccount.objects.create(
        student=student_user,
        school=school,
        balance=Decimal('0.00'),
    )

    body_dict = {"id": "tx-credit-001", "type": "cardTransaction"}
    mock_tx = {"invoiceNumber": "INV-2026-06-S1-0001", "amount": "60.00"}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value=mock_tx,
    ):
        response = make_helcim_signed_request(api_client, body_dict, webhook_id="msg-credit-001")

    assert response.status_code == 200

    # CreditTransaction must be created
    assert CreditTransaction.objects.filter(
        type='pre_billing_payment',
        amount=Decimal('60.00'),
    ).count() == 1

    # Balance must be incremented
    account.refresh_from_db()
    assert account.balance == Decimal('60.00')

    # PreBillingInvoice status must be 'paid'
    invoice.refresh_from_db()
    assert invoice.status == 'paid'

    # HelcimWebhookEvent.school must be set
    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="tx-credit-001")
    assert event.school_id == school.pk


@pytest.mark.django_db
def test_webhook_credit_unresolved_invoice_id_returns_200_no_credit(
    api_client, school, student_user
):
    """
    Helcim GET returns an invoiceNumber that does not match any PreBillingInvoice
    → 200, no CreditTransaction, event.school remains None (D-04).

    RED until Plan 03 implements the credit resolution block (currently no lookup
    is performed at all).
    """
    body_dict = {"id": "tx-unresolved-001", "type": "cardTransaction"}
    mock_tx = {"invoiceNumber": "INV-DOES-NOT-EXIST", "amount": "60.00"}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value=mock_tx,
    ):
        response = make_helcim_signed_request(api_client, body_dict, webhook_id="msg-unresolved-001")

    assert response.status_code == 200
    assert CreditTransaction.objects.count() == 0

    # Event row must exist but school FK must be None (D-04: unresolved → no school set)
    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="tx-unresolved-001")
    assert event.school_id is None


@pytest.mark.django_db
def test_webhook_credit_missing_student_credit_account_returns_200_no_credit(
    api_client, school, student_user
):
    """
    PreBillingInvoice exists but no StudentCreditAccount for this student
    → 200, no CreditTransaction, invoice.status NOT changed to 'paid' (D-04).

    RED until Plan 03 implements credit resolution. If Plan 03 adopts lazy
    account creation for the webhook path this test body will be updated then
    — leave assertion as-is to drive that decision.
    """
    # Invoice exists but NO StudentCreditAccount created
    invoice = PreBillingInvoice.objects.create(
        student=student_user,
        school=school,
        status='sent',
        amount=Decimal('60.00'),
        period_start='2026-06-01',
        period_end='2026-06-30',
        helcim_invoice_id='INV-2026-06-S1-0002',
    )

    body_dict = {"id": "tx-noaccount-001", "type": "cardTransaction"}
    mock_tx = {"invoiceNumber": "INV-2026-06-S1-0002", "amount": "60.00"}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value=mock_tx,
    ):
        response = make_helcim_signed_request(api_client, body_dict, webhook_id="msg-noaccount-001")

    assert response.status_code == 200
    assert CreditTransaction.objects.count() == 0

    invoice.refresh_from_db()
    assert invoice.status != 'paid'


@pytest.mark.django_db
def test_webhook_credit_zero_amount_event_skips_credit_block(api_client, school):
    """
    Secondary GET raises HelcimAPIError → event stored with amount=0.00.
    Credit block requires amount > 0 (Pitfall 1 guard: `if event.amount > Decimal('0.00')`).
    → No CreditTransaction, no IntegrityError.

    RED until Plan 03 adds the `if event.amount > Decimal('0.00')` guard before
    the credit block — currently the block does not exist so no guard is needed yet.
    This test verifies the guard is present after Plan 03.
    """
    body_dict = {"id": "tx-zeroamt-001", "type": "cardTransaction"}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        side_effect=HelcimAPIError("API down", status_code=503),
    ):
        response = make_helcim_signed_request(api_client, body_dict, webhook_id="msg-zeroamt-001")

    assert response.status_code == 200
    assert CreditTransaction.objects.count() == 0

    # Event must be stored with amount=0.00 (existing Phase 18 fallback behaviour)
    event = HelcimWebhookEvent.objects.get(helcim_transaction_id="tx-zeroamt-001")
    assert event.amount == Decimal('0.00')


@pytest.mark.django_db
def test_webhook_credit_blank_invoice_id_skips_credit_block(api_client, school):
    """
    Helcim GET returns blank invoiceNumber → credit block skipped (D-04: empty
    invoice_id is also an unresolved case; no PreBillingInvoice can match "").
    → No CreditTransaction.

    RED until Plan 03 implements the `if event.invoice_id and ...` guard.
    """
    body_dict = {"id": "tx-blankinv-001", "type": "cardTransaction"}
    mock_tx = {"invoiceNumber": "", "amount": "60.00"}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value=mock_tx,
    ):
        response = make_helcim_signed_request(api_client, body_dict, webhook_id="msg-blankinv-001")

    assert response.status_code == 200
    assert CreditTransaction.objects.count() == 0


@pytest.mark.django_db
def test_webhook_credit_duplicate_post_does_not_double_apply(
    api_client, school, student_user
):
    """
    Two identical signed POSTs → second returns {"status": "duplicate"} and does
    NOT create a second CreditTransaction (REC-01 idempotency guard).

    After first POST: 1 CreditTransaction, balance=60.00, event count=1.
    After second POST: still 1 CreditTransaction, balance still 60.00, event count still 1.

    RED until Plan 03 implements credit resolution (currently neither POST creates a
    CreditTransaction).
    """
    invoice = PreBillingInvoice.objects.create(
        student=student_user,
        school=school,
        status='sent',
        amount=Decimal('60.00'),
        period_start='2026-06-01',
        period_end='2026-06-30',
        helcim_invoice_id='INV-2026-06-S1-0003',
    )
    account = StudentCreditAccount.objects.create(
        student=student_user,
        school=school,
        balance=Decimal('0.00'),
    )

    body_dict = {"id": "tx-idempotent-001", "type": "cardTransaction"}
    mock_tx = {"invoiceNumber": "INV-2026-06-S1-0003", "amount": "60.00"}

    with mock.patch(
        "billing.views.webhooks.HelcimClient.get_card_transaction",
        return_value=mock_tx,
    ):
        r1 = make_helcim_signed_request(api_client, body_dict, webhook_id="msg-idempotent-001")
        r2 = make_helcim_signed_request(api_client, body_dict, webhook_id="msg-idempotent-001")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.data == {"status": "duplicate"}

    # Only one CreditTransaction must exist after two POSTs
    assert CreditTransaction.objects.count() == 1

    # Balance must not have been applied twice
    account.refresh_from_db()
    assert account.balance == Decimal('60.00')

    # Only one HelcimWebhookEvent row (idempotency)
    assert HelcimWebhookEvent.objects.filter(helcim_transaction_id="tx-idempotent-001").count() == 1
