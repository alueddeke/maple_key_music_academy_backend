"""
Unit tests for billing.services.ledger.post (MAP-186).

The ledger is the single writer of StudentCreditAccount.balance. Every row
carries a non-null source; only pre_billing_payment, waived_rollover and
lesson_charge move the balance; forfeited and shortfall are informational.

Invariant asserted throughout:
    balance == Σ(pre_billing_payment + waived_rollover) − Σ(lesson_charge)

Assertions are on outcomes (row state, balance, raised errors) — never on the
lock call or internal order. Amounts are generated, not literals tied to any
business rate.
"""
import random
from datetime import date, time
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import Sum

from billing.models import (
    BatchLessonItem,
    CreditTransaction,
    HelcimWebhookEvent,
    Lesson,
    MonthlyInvoiceBatch,
    PreBillingInvoice,
    StudentCreditAccount,
)
from billing.services import ledger

ZERO = Decimal('0.00')
MOVES_UP = ('pre_billing_payment', 'waived_rollover')
MOVES_DOWN = ('lesson_charge',)
NEUTRAL = ('forfeited', 'shortfall')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _account(student, school, balance=ZERO):
    return StudentCreditAccount.objects.create(student=student, school=school, balance=balance)


def _batch_item(teacher, school, student, day=1):
    batch, _ = MonthlyInvoiceBatch.objects.get_or_create(
        teacher=teacher, school=school, month=3, year=2026,
    )
    return BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=date(2026, 3, day),
        start_time=time(10, 0),
        duration=Decimal('1.0'),
        lesson_type='online',
        teacher_rate=Decimal('1.00'),
        student_rate=Decimal('1.00'),
        status='completed',
    )


def _event(tx_id):
    return HelcimWebhookEvent.objects.create(
        helcim_transaction_id=tx_id,
        raw_payload={'id': tx_id},
        amount=Decimal('1.00'),
    )


def _invoice(student, school):
    return PreBillingInvoice.objects.create(
        student=student, school=school, status='sent', amount=Decimal('1.00'),
        period_start=date(2026, 3, 1), period_end=date(2026, 3, 31),
    )


def _expected_balance(account):
    rows = CreditTransaction.objects.filter(account=account)
    up = rows.filter(type__in=MOVES_UP).aggregate(t=Sum('amount'))['t'] or ZERO
    down = rows.filter(type__in=MOVES_DOWN).aggregate(t=Sum('amount'))['t'] or ZERO
    return up - down


def _assert_invariant(account):
    account.refresh_from_db()
    assert account.balance == _expected_balance(account)
    for row in CreditTransaction.objects.filter(account=account, legacy=False):
        assert any([
            row.source_event_id, row.source_invoice_id,
            row.source_batch_item_id, row.source_lesson_id,
        ]), f'row {row.pk} ({row.type}) has no source'


@pytest.fixture
def item(teacher_user, school, student_user):
    return _batch_item(teacher_user, school, student_user)


# ---------------------------------------------------------------------------
# Balance effect per type
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBalanceEffect:

    @pytest.mark.parametrize('tx_type', MOVES_UP)
    def test_payment_and_rollover_increase_balance(self, school, student_user, item, tx_type):
        account = _account(student_user, school)
        first, second = Decimal('12.50'), Decimal('7.25')
        with transaction.atomic():
            ledger.post(account, type=tx_type, amount=first, source_batch_item=item)
            row = ledger.post(account, type=tx_type, amount=second, source_batch_item=item)

        account.refresh_from_db()
        assert account.balance == first + second
        assert row.type == tx_type and row.amount == second
        _assert_invariant(account)

    def test_lesson_charge_decreases_balance(self, school, student_user, item):
        funded = Decimal('30.00')
        charged = Decimal('11.00')
        account = _account(student_user, school)
        with transaction.atomic():
            ledger.post(account, type='pre_billing_payment', amount=funded, source_batch_item=item)
            ledger.post(account, type='lesson_charge', amount=charged, source_batch_item=item)

        account.refresh_from_db()
        assert account.balance == funded - charged
        _assert_invariant(account)

    @pytest.mark.parametrize('tx_type', NEUTRAL)
    def test_forfeited_and_shortfall_are_balance_neutral(self, school, student_user, item, tx_type):
        account = _account(student_user, school, balance=Decimal('5.00'))
        with transaction.atomic():
            row = ledger.post(account, type=tx_type, amount=Decimal('99.00'), source_batch_item=item)

        account.refresh_from_db()
        assert account.balance == Decimal('5.00')
        assert CreditTransaction.objects.filter(pk=row.pk, type=tx_type).exists()

    def test_post_updates_the_callers_instance(self, school, student_user, item):
        account = _account(student_user, school)
        with transaction.atomic():
            ledger.post(account, type='waived_rollover', amount=Decimal('4.00'), source_batch_item=item)
        assert account.balance == Decimal('4.00')


# ---------------------------------------------------------------------------
# Validation: source required, amount > 0, known type, legacy untouched
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestValidation:

    def test_post_requires_a_source(self, school, student_user):
        account = _account(student_user, school)
        with pytest.raises(ValueError):
            with transaction.atomic():
                ledger.post(account, type='pre_billing_payment', amount=Decimal('1.00'))
        assert CreditTransaction.objects.count() == 0
        account.refresh_from_db()
        assert account.balance == ZERO

    @pytest.mark.parametrize('amount', [Decimal('0.00'), Decimal('-0.01'), None])
    def test_post_rejects_non_positive_amount(self, school, student_user, item, amount):
        account = _account(student_user, school, balance=Decimal('3.00'))
        with pytest.raises(ValueError):
            with transaction.atomic():
                ledger.post(account, type='lesson_charge', amount=amount, source_batch_item=item)
        assert CreditTransaction.objects.count() == 0
        account.refresh_from_db()
        assert account.balance == Decimal('3.00')

    def test_post_rejects_unknown_type(self, school, student_user, item):
        account = _account(student_user, school)
        with pytest.raises(ValueError):
            with transaction.atomic():
                ledger.post(account, type='refund', amount=Decimal('1.00'), source_batch_item=item)
        assert CreditTransaction.objects.count() == 0

    def test_post_never_sets_legacy(self, school, student_user, item):
        account = _account(student_user, school)
        with transaction.atomic():
            row = ledger.post(account, type='forfeited', amount=Decimal('1.00'), source_batch_item=item)
        row.refresh_from_db()
        assert row.legacy is False

    def test_every_source_kind_is_accepted(self, school, teacher_user, student_user, item):
        account = _account(student_user, school)
        lesson = Lesson.objects.filter(student=student_user).first()
        sources = [
            {'source_event': _event('tx-ledger-src-1')},
            {'source_invoice': _invoice(student_user, school)},
            {'source_batch_item': item},
            {'source_lesson': lesson},
        ]
        with transaction.atomic():
            for src in sources:
                ledger.post(account, type='waived_rollover', amount=Decimal('1.00'), **src)
        assert CreditTransaction.objects.filter(account=account).count() == len(sources)
        _assert_invariant(account)

    def test_charge_above_balance_raises_and_leaves_ledger_unchanged(
        self, school, student_user, item,
    ):
        """credit_account_balance_non_negative still guards: no clamp, no row."""
        account = _account(student_user, school)
        with transaction.atomic():
            ledger.post(account, type='pre_billing_payment', amount=Decimal('10.00'), source_batch_item=item)
        rows_before = CreditTransaction.objects.filter(account=account).count()

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ledger.post(account, type='lesson_charge', amount=Decimal('10.01'), source_batch_item=item)

        assert CreditTransaction.objects.filter(account=account).count() == rows_before
        account.refresh_from_db()
        assert account.balance == Decimal('10.00')
        _assert_invariant(account)


# ---------------------------------------------------------------------------
# Property test: random sequences hold the invariant
# ---------------------------------------------------------------------------

def _cents(rng, lo=1, hi=20000):
    return (Decimal(rng.randint(lo, hi)) / Decimal(100)).quantize(Decimal('0.01'))


@pytest.mark.django_db
@pytest.mark.parametrize('seed', [1, 7, 42, 1234, 99991])
def test_random_sequences_hold_the_invariant(school, teacher_user, student_user, seed):
    """
    Random sequence of webhook credit / approval (with and without enough
    balance) / payroll forfeit / waived rollover on a fresh account.

    'approval' mirrors the approval rule: charge = min(balance, amount) posted
    as lesson_charge; the remainder as an informational shortfall. 'overcharge'
    attempts a lesson_charge above the balance — the DB rejects it and nothing
    changes. After every step: balance == Σ(payment + rollover) − Σ(lesson_charge)
    and every legacy=False row has a source.
    """
    rng = random.Random(seed)
    account = _account(student_user, school)
    ops = ('payment', 'rollover', 'approval', 'forfeit', 'overcharge')

    for step in range(40):
        op = rng.choice(ops)
        amount = _cents(rng)
        item = _batch_item(teacher_user, school, student_user, day=1 + step % 28)
        account.refresh_from_db()

        if op == 'payment':
            with transaction.atomic():
                ledger.post(account, type='pre_billing_payment', amount=amount,
                            source_event=_event(f'tx-{seed}-{step}'))
        elif op == 'rollover':
            with transaction.atomic():
                ledger.post(account, type='waived_rollover', amount=amount, source_batch_item=item)
        elif op == 'approval':
            charge = min(account.balance, amount)
            remainder = amount - charge
            with transaction.atomic():
                if charge > ZERO:
                    ledger.post(account, type='lesson_charge', amount=charge, source_batch_item=item)
                if remainder > ZERO:
                    ledger.post(account, type='shortfall', amount=remainder, source_batch_item=item)
        elif op == 'forfeit':
            with transaction.atomic():
                ledger.post(account, type='forfeited', amount=amount, source_batch_item=item)
        else:  # overcharge
            over = account.balance + Decimal('0.01')
            with pytest.raises(IntegrityError):
                with transaction.atomic():
                    ledger.post(account, type='lesson_charge', amount=over, source_batch_item=item)

        _assert_invariant(account)

    assert CreditTransaction.objects.filter(account=account).exists()
