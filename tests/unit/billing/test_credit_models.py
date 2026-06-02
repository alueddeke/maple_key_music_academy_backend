"""
Unit tests for credit ledger models and forfeited/waived terminology changes.

Protects: StudentCreditAccount constraints (D-10, D-11, D-14), CreditTransaction
type validation (D-12, D-13), Lesson/BatchLessonItem terminology (CRED-01),
and BatchLessonItem.calculate_student_charge / calculate_teacher_payment
semantics (D-02).

Design follows D-06 testing principles (Phase 16 CONTEXT.md):
  1. Fail safely, fail fast, fail closed — no open states, no default values, everything explicit.
  2. 100% backend test coverage — every code path exercised.
  3. Every path needs 1 happy path + 1 failing path — contrast ensures accuracy.
  4. Test behaviour, not implementation — what the code does, not how it does it.
  5. Ideal and non-ideal circumstances covered.
  6. No implicit defaults — all assertions explicit; never pass silently with missing data.
"""

import pytest
from decimal import Decimal
from datetime import date, time
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from billing.models import (
    Lesson, BatchLessonItem, MonthlyInvoiceBatch,
    StudentCreditAccount, CreditTransaction,
)
from billing.serializers import BatchLessonItemSerializer


# ---------------------------------------------------------------------------
# Factory helpers — explicit sentinel values per D-06 (no implicit defaults)
# ---------------------------------------------------------------------------

def _make_batch(teacher, school, batch_number=None, month=1, year=2026):
    """Create a MonthlyInvoiceBatch; auto-generates batch_number if not provided."""
    kwargs = dict(teacher=teacher, school=school, month=month, year=year)
    if batch_number:
        kwargs['batch_number'] = batch_number
    return MonthlyInvoiceBatch.objects.create(**kwargs)


def _make_batch_lesson_item(
    batch,
    student,
    status='confirmed',
    teacher_rate=Decimal('45.00'),
    student_rate=Decimal('60.00'),
    duration=Decimal('1.0'),
):
    """Create a BatchLessonItem with explicit sentinel rates; hard-codes date/time."""
    return BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=date(2026, 1, 15),
        start_time=time(10, 0),
        duration=duration,
        lesson_type='online',
        teacher_rate=teacher_rate,
        student_rate=student_rate,
        status=status,
    )


def _make_credit_account(student, school, balance=Decimal('0.00')):
    """Create a StudentCreditAccount with explicit balance."""
    return StudentCreditAccount.objects.create(
        student=student,
        school=school,
        balance=balance,
    )


# ---------------------------------------------------------------------------
# Class 1 — Terminology status tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTerminologyStatuses:
    """CRED-01: forfeited/waived statuses present; cancelled_by_type removed."""

    def test_lesson_status_contains_forfeited_and_waived(self):
        """Lesson.LESSON_STATUS contains forfeited, waived, AND cancelled (CRED-01)."""
        status_keys = [code for code, _ in Lesson.LESSON_STATUS]
        assert 'forfeited' in status_keys
        assert 'waived' in status_keys
        assert 'cancelled' in status_keys  # backward compat preserved

    def test_batch_lesson_item_has_no_cancelled_by_type(self):
        """cancelled_by_type field was removed from BatchLessonItem in Plan 01 (CRED-01)."""
        field_names = [f.name for f in BatchLessonItem._meta.get_fields()]
        assert 'cancelled_by_type' not in field_names

    def test_batch_lesson_item_accepts_forfeited_status(self, school, teacher_user, student_user):
        """BatchLessonItem.status='forfeited' is a valid choice and round-trips (CRED-01 happy)."""
        batch = _make_batch(teacher_user, school)
        item = _make_batch_lesson_item(batch, student_user, status='forfeited')
        item.refresh_from_db()
        assert item.status == 'forfeited'

    def test_batch_lesson_item_accepts_waived_status(self, school, teacher_user, student_user):
        """BatchLessonItem.status='waived' is a valid choice and round-trips (CRED-01 happy)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-W1')
        item = _make_batch_lesson_item(batch, student_user, status='waived')
        item.refresh_from_db()
        assert item.status == 'waived'

    def test_batch_lesson_item_rejects_unknown_status(self, school, teacher_user, student_user):
        """BatchLessonItem with unknown status fails full_clean() at the choices layer (failing path)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-U1')
        item = _make_batch_lesson_item(batch, student_user, status='confirmed')
        item.status = 'invalid_unknown_status'
        with pytest.raises(ValidationError):
            item.full_clean()

    def test_serializer_no_cancelled_by_type(self):
        """BatchLessonItemSerializer.Meta.fields does not include 'cancelled_by_type' (CRED-01)."""
        assert 'cancelled_by_type' not in BatchLessonItemSerializer.Meta.fields


# ---------------------------------------------------------------------------
# Class 2 — StudentCreditAccount constraints
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestStudentCreditAccountConstraints:
    """D-10, D-11, D-14: balance CheckConstraint, unique_together, select_for_update pattern."""

    def test_balance_check_constraint_rejects_negative(self, school, student_user):
        """DB-level CheckConstraint fires when balance < 0 (D-11 failing path)."""
        account = _make_credit_account(student_user, school, balance=Decimal('0.00'))
        account.balance = Decimal('-0.01')
        with transaction.atomic():
            with pytest.raises(IntegrityError):
                account.save()

    def test_balance_zero_is_accepted(self, school, student_user):
        """Balance == 0 is the boundary happy path — CheckConstraint allows it (D-11)."""
        account = _make_credit_account(student_user, school, balance=Decimal('0.00'))
        account.refresh_from_db()
        assert account.balance == Decimal('0.00')

    def test_balance_positive_is_accepted(self, school, student_user):
        """Balance = 123.45 round-trips cleanly (D-11 happy path)."""
        account = _make_credit_account(student_user, school, balance=Decimal('123.45'))
        account.refresh_from_db()
        assert account.balance == Decimal('123.45')

    def test_unique_constraint_on_student_school(self, school, student_user):
        """Creating a second StudentCreditAccount for same (student, school) raises IntegrityError (D-10 failing path)."""
        _make_credit_account(student_user, school)
        with transaction.atomic():
            with pytest.raises(IntegrityError):
                StudentCreditAccount.objects.create(
                    student=student_user,
                    school=school,
                    balance=Decimal('0.00'),
                )

    def test_select_for_update_used_inside_atomic(self, school, student_user):
        """Phase 20 contract (D-14): select_for_update() inside atomic reads correct balance after write."""
        _make_credit_account(student_user, school, balance=Decimal('50.00'))
        with transaction.atomic():
            obj = StudentCreditAccount.objects.select_for_update().get(
                student=student_user,
                school=school,
            )
            obj.balance += Decimal('10.00')
            obj.save()
        obj.refresh_from_db()
        assert obj.balance == Decimal('60.00')


# ---------------------------------------------------------------------------
# Class 3 — CreditTransaction constraints
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCreditTransactionConstraints:
    """D-12, D-13: valid type choices enforced at full_clean; direct school FK present."""

    def test_valid_types_accepted(self, school, student_user):
        """All 3 CreditTransaction type values create successfully (D-12 happy)."""
        account = _make_credit_account(student_user, school)
        for tx_type in ('pre_billing_payment', 'forfeited', 'waived_rollover'):
            tx = CreditTransaction.objects.create(
                account=account,
                school=school,
                type=tx_type,
                amount=Decimal('10.00'),
            )
            assert tx.type == tx_type

    def test_invalid_type_rejected_by_full_clean(self, school, student_user):
        """CreditTransaction with invalid type raises ValidationError on full_clean() (D-12 failing path)."""
        account = _make_credit_account(student_user, school)
        tx = CreditTransaction(
            account=account,
            school=school,
            type='invalid_type',
            amount=Decimal('10.00'),
        )
        with pytest.raises(ValidationError):
            tx.full_clean()

    def test_amount_must_be_positive_decimal(self, school, student_user):
        """Amount = 50.00 stores and reads back as exact Decimal (D-07 happy path)."""
        account = _make_credit_account(student_user, school)
        tx = CreditTransaction.objects.create(
            account=account,
            school=school,
            type='pre_billing_payment',
            amount=Decimal('50.00'),
        )
        tx.refresh_from_db()
        assert tx.amount == Decimal('50.00')

    def test_school_fk_is_direct_not_through_account(self, school, student_user):
        """CreditTransaction.school_id is set directly (denormalized FK per D-13)."""
        account = _make_credit_account(student_user, school)
        tx = CreditTransaction.objects.create(
            account=account,
            school=school,
            type='forfeited',
            amount=Decimal('20.00'),
        )
        assert tx.school_id is not None
        assert tx.school_id == account.school_id


# ---------------------------------------------------------------------------
# Class 4 — Calculation method semantics
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCalculationMethodSemantics:
    """D-02: calculate_teacher_payment and calculate_student_charge semantics."""

    def test_calculate_teacher_payment_cancelled_is_zero(self, school, teacher_user, student_user):
        """Regression (D-02): cancelled lesson → teacher payment = 0."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-TC1')
        item = _make_batch_lesson_item(
            batch, student_user, status='cancelled',
            teacher_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )
        assert item.calculate_teacher_payment() == Decimal('0.00')

    def test_calculate_teacher_payment_forfeited_is_nonzero(self, school, teacher_user, student_user):
        """D-02 happy: forfeited lesson → teacher is paid (teacher_rate × duration)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-TF1')
        item = _make_batch_lesson_item(
            batch, student_user, status='forfeited',
            teacher_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )
        assert item.calculate_teacher_payment() == Decimal('45.00')

    def test_calculate_teacher_payment_waived_is_nonzero(self, school, teacher_user, student_user):
        """D-02 happy: waived lesson → teacher is paid (teacher_rate × duration)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-TW1')
        item = _make_batch_lesson_item(
            batch, student_user, status='waived',
            teacher_rate=Decimal('45.00'), duration=Decimal('1.0'),
        )
        assert item.calculate_teacher_payment() == Decimal('45.00')

    def test_calculate_student_charge_cancelled_is_zero(self, school, teacher_user, student_user):
        """Regression (D-02): cancelled lesson → student charge = 0."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-SC1')
        item = _make_batch_lesson_item(
            batch, student_user, status='cancelled',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )
        assert item.calculate_student_charge() == Decimal('0.00')

    def test_calculate_student_charge_waived_is_zero(self, school, teacher_user, student_user):
        """D-02: waived lesson → school absorbs cost, student charge = 0."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-SW1')
        item = _make_batch_lesson_item(
            batch, student_user, status='waived',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )
        assert item.calculate_student_charge() == Decimal('0.00')

    def test_calculate_student_charge_forfeited_is_nonzero(self, school, teacher_user, student_user):
        """D-02: forfeited lesson → student IS charged; Phase 20 reconciles via credit (student_rate × duration)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-SF1')
        item = _make_batch_lesson_item(
            batch, student_user, status='forfeited',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )
        assert item.calculate_student_charge() == Decimal('60.00')

    def test_calculate_student_charge_trial_is_zero(self, school, teacher_user, student_user):
        """Regression D-05 backward compat: trial lesson → student charge = 0."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-ST1')
        item = _make_batch_lesson_item(
            batch, student_user, status='trial',
            student_rate=Decimal('60.00'), duration=Decimal('1.0'),
        )
        assert item.calculate_student_charge() == Decimal('0.00')
