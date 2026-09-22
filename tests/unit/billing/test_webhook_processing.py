"""
MAP-216: a card payment credits the wallet with at most what the invoice still
owed; anything above that is recorded on the event as a fee and never reaches
the balance.

Testing notes
  * Service boundary: process_webhook_event on events already past enrichment
    (no Helcim call), same fixture shape as the MAP-180 tests.
  * Amounts derive from INVOICE_AMOUNT and FEE — the rule under test is
    "credit = min(payment, still owed)", not a particular fee percentage.
  * Assertions are on outcomes: ledger rows, account balance, invoice status,
    event status + fee_amount.
"""
from decimal import Decimal

import pytest

from billing.models import (
    CreditTransaction,
    HelcimWebhookEvent,
    PreBillingInvoice,
    StudentCreditAccount,
)
from billing.services.webhook_processing import RETRYABLE_STATES, process_webhook_event

INVOICE_AMOUNT = Decimal("100.00")
FEE = Decimal("3.00")
FIRST_PARTIAL = Decimal("40.00")
ZERO = Decimal("0.00")


def _invoice_and_account(school, student, number):
    invoice = PreBillingInvoice.objects.create(
        student=student, school=school, status="sent", amount=INVOICE_AMOUNT,
        period_start="2026-09-01", period_end="2026-09-30",
        helcim_invoice_number=number,
    )
    account = StudentCreditAccount.objects.create(student=student, school=school, balance=ZERO)
    return invoice, account


def _approved_purchase(tx_id, number, amount):
    """An event past enrichment (no Helcim call needed), still pending."""
    return HelcimWebhookEvent.objects.create(
        helcim_transaction_id=tx_id,
        raw_payload={"id": tx_id, "type": "cardTransaction"},
        invoice_id=number,
        amount=amount,
        transaction_status="APPROVED",
        transaction_type="purchase",
        processing_status="pending",
    )


def _credited_amounts(account):
    return list(
        CreditTransaction.objects
        .filter(account=account, type="pre_billing_payment")
        .order_by("id")
        .values_list("amount", flat=True)
    )


@pytest.mark.django_db
def test_payment_above_invoice_credits_invoice_amount_and_records_fee(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, "INV-FEE-1")
    event = _approved_purchase("tx-fee-1", "INV-FEE-1", INVOICE_AMOUNT + FEE)

    process_webhook_event(event)

    assert _credited_amounts(account) == [INVOICE_AMOUNT]
    account.refresh_from_db()
    assert account.balance == INVOICE_AMOUNT
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    event.refresh_from_db()
    assert event.processing_status == "credited"
    assert event.fee_amount == FEE
    assert event.amount == INVOICE_AMOUNT + FEE


@pytest.mark.django_db
def test_second_partial_with_fee_credits_only_what_was_still_owed(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, "INV-FEE-2")
    still_owed = INVOICE_AMOUNT - FIRST_PARTIAL
    first = _approved_purchase("tx-fee-2a", "INV-FEE-2", FIRST_PARTIAL)
    second = _approved_purchase("tx-fee-2b", "INV-FEE-2", still_owed + FEE)

    process_webhook_event(first)

    invoice.refresh_from_db()
    assert invoice.status == "sent"
    first.refresh_from_db()
    assert first.processing_status == "credited_partial"
    assert first.fee_amount == ZERO

    process_webhook_event(second)

    assert _credited_amounts(account) == [FIRST_PARTIAL, still_owed]
    account.refresh_from_db()
    assert account.balance == INVOICE_AMOUNT
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    second.refresh_from_db()
    assert second.processing_status == "credited"
    assert second.fee_amount == FEE


@pytest.mark.django_db
def test_prior_coverage_counts_credited_amounts_not_gross(school, student_user):
    """A first payment that carried a fee must not shrink what the next one may credit."""
    invoice, account = _invoice_and_account(school, student_user, "INV-FEE-3")
    first = _approved_purchase("tx-fee-3a", "INV-FEE-3", FIRST_PARTIAL)
    process_webhook_event(first)
    # Rewrite the first event as gross = credited + fee (what a fee-carrying
    # partial looks like once recorded): credited stays FIRST_PARTIAL.
    HelcimWebhookEvent.objects.filter(pk=first.pk).update(
        amount=FIRST_PARTIAL + FEE, fee_amount=FEE,
    )
    still_owed = INVOICE_AMOUNT - FIRST_PARTIAL
    second = _approved_purchase("tx-fee-3b", "INV-FEE-3", still_owed)

    process_webhook_event(second)

    assert _credited_amounts(account) == [FIRST_PARTIAL, still_owed]
    second.refresh_from_db()
    assert second.fee_amount == ZERO
    assert second.processing_status == "credited"
    invoice.refresh_from_db()
    assert invoice.status == "paid"


@pytest.mark.django_db
def test_exact_payment_credits_full_amount_with_zero_fee(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, "INV-FEE-4")
    event = _approved_purchase("tx-fee-4", "INV-FEE-4", INVOICE_AMOUNT)

    process_webhook_event(event)

    assert _credited_amounts(account) == [INVOICE_AMOUNT]
    account.refresh_from_db()
    assert account.balance == INVOICE_AMOUNT
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    event.refresh_from_db()
    assert event.processing_status == "credited"
    assert event.fee_amount == ZERO


@pytest.mark.django_db
def test_payment_on_already_covered_invoice_needs_attention_no_ledger_row(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, "INV-FEE-5")
    process_webhook_event(_approved_purchase("tx-fee-5a", "INV-FEE-5", INVOICE_AMOUNT + FEE))
    extra = _approved_purchase("tx-fee-5b", "INV-FEE-5", INVOICE_AMOUNT + FEE)

    process_webhook_event(extra)

    assert _credited_amounts(account) == [INVOICE_AMOUNT]
    assert not CreditTransaction.objects.filter(source_event=extra).exists()
    account.refresh_from_db()
    assert account.balance == INVOICE_AMOUNT
    extra.refresh_from_db()
    assert extra.processing_status == "needs_attention"
    assert extra.processing_status not in RETRYABLE_STATES

    # Terminal: a retry changes nothing.
    process_webhook_event(extra)
    extra.refresh_from_db()
    assert extra.processing_status == "needs_attention"
    assert _credited_amounts(account) == [INVOICE_AMOUNT]


@pytest.mark.django_db
def test_replay_of_capped_event_posts_nothing_twice(school, student_user):
    invoice, account = _invoice_and_account(school, student_user, "INV-FEE-6")
    event = _approved_purchase("tx-fee-6", "INV-FEE-6", INVOICE_AMOUNT + FEE)
    process_webhook_event(event)

    replayed = HelcimWebhookEvent.objects.get(pk=event.pk)
    process_webhook_event(replayed)

    assert _credited_amounts(account) == [INVOICE_AMOUNT]
    account.refresh_from_db()
    assert account.balance == INVOICE_AMOUNT
    replayed.refresh_from_db()
    assert replayed.processing_status == "credited"
    assert replayed.fee_amount == FEE
