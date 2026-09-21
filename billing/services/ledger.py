"""
Credit ledger — the single writer for StudentCreditAccount.balance (MAP-186).

Every change to a student's balance is exactly one CreditTransaction row with
a non-null source reference, posted here under select_for_update. Callers
never touch `account.balance` directly.

Balance effect by type:
    pre_billing_payment  +amount
    waived_rollover      +amount
    lesson_charge        -amount
    forfeited            0 (informational: the no-show record)
    shortfall            0 (informational: uncovered remainder at approval)

Invariant (for accounts created after migration 0074):
    balance == Σ(pre_billing_payment + waived_rollover) − Σ(lesson_charge)

`post` runs inside the caller's transaction.atomic() block. It never opens an
outer transaction of its own: select_for_update outside atomic raises, and a
lesson_charge that would take the balance below zero fails on the
credit_account_balance_non_negative constraint instead of being clamped.
"""
from decimal import Decimal

from ..models import CreditTransaction, StudentCreditAccount

BALANCE_EFFECT = {
    'pre_billing_payment': Decimal('1'),
    'waived_rollover': Decimal('1'),
    'lesson_charge': Decimal('-1'),
    'forfeited': Decimal('0'),
    'shortfall': Decimal('0'),
}


def post(
    account,
    *,
    type,
    amount,
    source_event=None,
    source_invoice=None,
    source_batch_item=None,
    source_lesson=None,
):
    """
    Lock the account row, write one CreditTransaction, apply the balance
    effect for `type`, save. Returns the CreditTransaction.

    Raises ValueError when amount <= 0, when no source is given, or when the
    type is unknown. Never sets `legacy`.
    """
    if type not in BALANCE_EFFECT:
        raise ValueError(f'ledger.post: unknown transaction type {type!r}')
    if amount is None or amount <= 0:
        raise ValueError(f'ledger.post: amount must be positive, got {amount!r}')
    if (
        source_event is None
        and source_invoice is None
        and source_batch_item is None
        and source_lesson is None
    ):
        raise ValueError('ledger.post: a source reference is required')

    locked = StudentCreditAccount.objects.select_for_update().get(pk=account.pk)

    row = CreditTransaction.objects.create(
        account=locked,
        school=locked.school,
        type=type,
        amount=amount,
        source_event=source_event,
        source_invoice=source_invoice,
        source_batch_item=source_batch_item,
        source_lesson=source_lesson,
    )

    effect = BALANCE_EFFECT[type]
    if effect:
        locked.balance = locked.balance + effect * amount
        locked.save(update_fields=['balance'])

    # Keep the caller's in-memory instance current — every existing caller
    # goes on using the object it passed in.
    account.balance = locked.balance
    return row
