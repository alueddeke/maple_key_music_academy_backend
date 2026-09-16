"""
MAP-180: one webhook event credits exactly once, under concurrency, whatever
the caller (webhook view, retry_webhook_events, direct service call).

Testing notes
  * The concurrency tests use @pytest.mark.django_db(transaction=True):
    select_for_update is invisible inside a wrapped test transaction.
  * They must run on Postgres (the api container / CI do); select_for_update
    is a no-op on SQLite — a green SQLite run proves nothing here.
  * pytest runs --no-migrations, so the partial UniqueConstraint
    one_credit_per_webhook_event is created from Meta.constraints and the
    tests see it; the migration is still required for production.
  * Assertions are on outcomes: CreditTransaction row count, account balance,
    event status, response body — never on the lock call or call order.
"""
import base64
import hashlib
import hmac
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.urls import reverse

from billing.models import (
    CreditTransaction,
    HelcimWebhookEvent,
    PreBillingInvoice,
    StudentCreditAccount,
)
from billing.services.webhook_processing import process_webhook_event

PATCH_TARGET = "billing.services.webhook_processing.HelcimClient.get_card_transaction"
AMOUNT = Decimal("60.00")


def _signed_post(api_client, body_dict, webhook_id):
    raw_body = json.dumps(body_dict).encode("utf-8")
    signed_content = f"{webhook_id}.1700000000.{raw_body.decode('utf-8')}"
    secret = base64.b64decode(settings.HELCIM_WEBHOOK_SECRET)
    digest = hmac.new(secret, signed_content.encode("utf-8"), hashlib.sha256).digest()
    return api_client.post(
        reverse("payment_callback"),
        data=raw_body,
        content_type="application/json",
        HTTP_WEBHOOK_ID=webhook_id,
        HTTP_WEBHOOK_TIMESTAMP="1700000000",
        HTTP_WEBHOOK_SIGNATURE=f"v1,{base64.b64encode(digest).decode('utf-8')}",
    )


def _invoice_and_account(school, student, number):
    invoice = PreBillingInvoice.objects.create(
        student=student, school=school, status="sent", amount=AMOUNT,
        period_start="2026-08-01", period_end="2026-08-31",
        helcim_invoice_number=number,
    )
    account = StudentCreditAccount.objects.create(student=student, school=school, balance=Decimal("0.00"))
    return invoice, account


def _retryable_enriched_event(tx_id, number, status="pending"):
    """An event past enrichment (no Helcim call needed) still in a retryable state."""
    return HelcimWebhookEvent.objects.create(
        helcim_transaction_id=tx_id,
        raw_payload={"id": tx_id, "type": "cardTransaction"},
        invoice_id=number,
        amount=AMOUNT,
        transaction_status="APPROVED",
        transaction_type="purchase",
        processing_status=status,
    )


def _in_thread(fn, barrier):
    """Run fn on its own DB connection after every worker reached the barrier."""
    def _go():
        connection.close()
        barrier.wait(timeout=10)
        try:
            return fn()
        finally:
            connection.close()
    return _go


def _assert_credited_once(event_id, account_id, invoice_id):
    assert CreditTransaction.objects.filter(source_event_id=event_id).count() == 1
    assert CreditTransaction.objects.count() == 1
    assert StudentCreditAccount.objects.get(pk=account_id).balance == AMOUNT
    assert HelcimWebhookEvent.objects.get(pk=event_id).processing_status == "credited"
    assert PreBillingInvoice.objects.get(pk=invoice_id).status == "paid"


# ---------------------------------------------------------------------------
# Acceptance: two callers processing the same retryable event concurrently
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_two_concurrent_callers_credit_exactly_once(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, "INV-IDEMP-1")
    event = _retryable_enriched_event("tx-idemp-1", "INV-IDEMP-1")
    barrier = threading.Barrier(2)

    def _process():
        ev = HelcimWebhookEvent.objects.get(pk=event.pk)   # each caller holds its own stale copy
        process_webhook_event(ev)
        return ev.processing_status

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_in_thread(_process, barrier)) for _ in range(2)]
        outcomes = [f.result(timeout=20) for f in futures]

    assert outcomes == ["credited", "credited"]
    _assert_credited_once(event.pk, account.pk, invoice.pk)


@pytest.mark.django_db(transaction=True)
def test_retry_command_racing_a_redelivery_credits_exactly_once(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, "INV-IDEMP-2")
    event = _retryable_enriched_event("tx-idemp-2", "INV-IDEMP-2", status="no_account")
    barrier = threading.Barrier(2)

    def _command():
        out = StringIO()
        call_command("retry_webhook_events", stdout=out)
        return out.getvalue()

    def _redelivery():
        ev = HelcimWebhookEvent.objects.get(pk=event.pk)
        process_webhook_event(ev)
        return ev.processing_status

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_cmd = ex.submit(_in_thread(_command, barrier))
        f_re = ex.submit(_in_thread(_redelivery, barrier))
        command_output = f_cmd.result(timeout=20)
        redelivery_outcome = f_re.result(timeout=20)

    assert "credited" in command_output
    assert redelivery_outcome == "credited"
    _assert_credited_once(event.pk, account.pk, invoice.pk)


# ---------------------------------------------------------------------------
# Acceptance: redelivery after credited
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_redelivery_after_credited_is_duplicate_and_changes_nothing(api_client, school, student_user):
    invoice, account = _invoice_and_account(school, student_user, "INV-IDEMP-3")
    event = _retryable_enriched_event("tx-idemp-3", "INV-IDEMP-3")
    process_webhook_event(event)
    assert HelcimWebhookEvent.objects.get(pk=event.pk).processing_status == "credited"

    with mock.patch(PATCH_TARGET) as mock_get:
        response = _signed_post(api_client, {"id": "tx-idemp-3", "type": "cardTransaction"}, "msg-idemp-3")

    assert response.status_code == 200
    assert response.data == {"status": "duplicate"}
    mock_get.assert_not_called()
    _assert_credited_once(event.pk, account.pk, invoice.pk)


# ---------------------------------------------------------------------------
# Database backstop: one credit per event, enforced by the constraint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_credit_already_posted_for_event_is_not_posted_again(school, student_user):
    """Event still retryable but its credit row already exists (constraint path):
    no second row, balance not incremented, event finalized credited."""
    invoice, account = _invoice_and_account(school, student_user, "INV-IDEMP-4")
    event = _retryable_enriched_event("tx-idemp-4", "INV-IDEMP-4")
    CreditTransaction.objects.create(
        account=account, school=school, type="pre_billing_payment", amount=AMOUNT, source_event=event,
    )
    account.balance = AMOUNT
    account.save()

    process_webhook_event(event)

    assert event.processing_status == "credited"
    assert CreditTransaction.objects.filter(source_event=event).count() == 1
    account.refresh_from_db()
    assert account.balance == AMOUNT


@pytest.mark.django_db
def test_database_rejects_second_credit_for_same_event(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, "INV-IDEMP-5")
    event = _retryable_enriched_event("tx-idemp-5", "INV-IDEMP-5")
    CreditTransaction.objects.create(
        account=account, school=school, type="pre_billing_payment", amount=AMOUNT, source_event=event,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CreditTransaction.objects.create(
                account=account, school=school, type="pre_billing_payment", amount=AMOUNT, source_event=event,
            )

    assert CreditTransaction.objects.filter(source_event=event).count() == 1


@pytest.mark.django_db
def test_batch_item_sourced_rows_coexist(school, teacher_user, student_user):
    """
    Forfeits / rollovers carry no event — they are sourced to a batch item
    (MAP-186). one_credit_per_webhook_event only constrains source_event, so
    several NULL-source_event rows coexist, each with its own item source.
    """
    from datetime import date, time
    from billing.models import BatchLessonItem, MonthlyInvoiceBatch

    invoice, account = _invoice_and_account(school, student_user, "INV-IDEMP-6")
    batch = MonthlyInvoiceBatch.objects.create(teacher=teacher_user, school=school, month=8, year=2026)
    for day in (3, 10):
        item = BatchLessonItem.objects.create(
            batch=batch, student=student_user, scheduled_date=date(2026, 8, day),
            start_time=time(10, 0), duration=Decimal("1.0"), lesson_type="online",
            teacher_rate=Decimal("1.00"), student_rate=Decimal("1.00"), status="waived",
        )
        CreditTransaction.objects.create(
            account=account, school=school, type="waived_rollover", amount=Decimal("5.00"),
            source_batch_item=item,
        )
    rows = CreditTransaction.objects.filter(account=account, source_event__isnull=True)
    assert rows.count() == 2
    assert rows.filter(source_batch_item__isnull=True).count() == 0
