"""
MAP-218: neutralize_test_accounts — closed id lists, dry run by default,
snapshot drift guard, one transaction, pre-state JSON + --revert.

The mechanism tests point the module's id lists and EXPECTED snapshot at
fixture accounts (small, deterministic). One data test pins the real
constants: every listed prod id must carry a snapshot row.
"""
from datetime import time
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from billing.management.commands import neutralize_test_accounts as cmd
from billing.models import (
    BillableContact,
    CreditTransaction,
    InvoiceSendItem,
    InvoiceSendRun,
    Lesson,
    MonthlyInvoiceBatch,
    PreBillingInvoice,
    RecurringLessonsSchedule,
    StudentCreditAccount,
    User,
)

TEST_DOMAIN = cmd.TEST_DOMAIN


def _user(school, user_id, user_type, first, last, email):
    return User.objects.create_user(
        id=user_id, email=email, password='x', user_type=user_type,
        first_name=first, last_name=last, school=school, is_approved=True,
    )


def _schedule(school, teacher, student):
    return RecurringLessonsSchedule.objects.create(
        school=school, teacher=teacher, student=student, day_of_week=0,
        start_time=time(15, 0), duration=Decimal('1.0'), lesson_type='online',
        teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'),
        is_active=True, start_date='2026-01-05',
    )


def _invoice(school, student, status, number):
    return PreBillingInvoice.objects.create(
        student=student, school=school, status=status, amount=Decimal('100.00'),
        period_start='2026-09-01', period_end='2026-09-30', helcim_invoice_number=number,
    )


@pytest.fixture
def world(school, monkeypatch):
    """Fixture accounts standing in for the prod lists (ids far from real ones)."""
    student = _user(school, 9001, 'student', 'Bill Test', 'Student', 'realparent@example.com')
    student2 = _user(school, 9002, 'student', 'Matt', 'Test', 'matt.test@example.com')
    test_teacher = _user(school, 9101, 'teacher', 'Test', 'Teacher', 'asd@example.com')
    kept = _user(school, 9003, 'teacher', 'Toni', 'Teacher Test', 'owner.login@example.com')
    duplicate = _user(school, 9108, 'teacher', 'William', 'Kervin', 'wmk@example.com')
    real_teacher = _user(school, 9105, 'teacher', 'Bill', 'Kervin', 'bill@example.com')
    real_student = _user(school, 9065, 'student', 'Ray', 'Smith', 'ray@example.com')

    contact = BillableContact.objects.create(
        school=school, student=student, email='realparent@example.com',
        first_name='Real', last_name='Parent',
    )
    sched_student = _schedule(school, real_teacher, student)
    sched_kept = _schedule(school, kept, student2)
    sched_real = _schedule(school, real_teacher, real_student)

    draft = _invoice(school, student, 'draft', 'MK-DRAFT-1')
    run = InvoiceSendRun.objects.create(school=school, period_start='2026-09-01', created_by=real_teacher)
    InvoiceSendItem.objects.create(run=run, invoice=draft, position=1, status='failed')
    paid = _invoice(school, student2, 'paid', 'MK-PAID-1')
    real_draft = _invoice(school, real_student, 'draft', 'MK-REAL-DRAFT')
    account = StudentCreditAccount.objects.create(student=student2, school=school, balance=Decimal('103.00'))
    lesson = Lesson.objects.create(
        teacher=real_teacher, student=student, school=school,
        scheduled_date=timezone.make_aware(timezone.datetime(2026, 9, 2, 15, 0)),
        duration=Decimal('1.0'), lesson_type='online',
        teacher_rate=Decimal('45.00'), student_rate=Decimal('60.00'), status='completed',
    )
    credit = CreditTransaction.objects.create(
        account=account, school=school, type='pre_billing_payment',
        amount=Decimal('103.00'), source_invoice=paid,
    )
    batch = MonthlyInvoiceBatch.objects.create(
        teacher=real_teacher, school=school, year=2026, month=9, status='draft',
    )

    monkeypatch.setattr(cmd, 'TEST_STUDENT_IDS', [student.id, student2.id])
    monkeypatch.setattr(cmd, 'TEST_TEACHER_IDS', [test_teacher.id])
    monkeypatch.setattr(cmd, 'KEEP_TEACHER_ID', kept.id)
    monkeypatch.setattr(cmd, 'DUPLICATE_TEACHER_ID', duplicate.id)
    monkeypatch.setattr(cmd, 'EXPECTED', {
        u.id: (u.first_name, u.last_name, u.email)
        for u in (student, student2, test_teacher, kept, duplicate)
    })
    return {
        'student': student, 'student2': student2, 'test_teacher': test_teacher,
        'kept': kept, 'duplicate': duplicate, 'real_teacher': real_teacher,
        'real_student': real_student, 'contact': contact,
        'sched_student': sched_student, 'sched_kept': sched_kept, 'sched_real': sched_real,
        'draft': draft, 'paid': paid, 'real_draft': real_draft, 'account': account,
        'lesson': lesson, 'credit': credit, 'batch': batch,
    }


def _run(*args):
    out = StringIO()
    call_command('neutralize_test_accounts', *args, stdout=out)
    return out.getvalue()


def _refresh(*objs):
    for o in objs:
        o.refresh_from_db()


@pytest.mark.django_db
def test_dry_run_changes_nothing_and_prints_plan(world):
    out = _run()

    assert 'Dry run' in out
    for line in (f"{world['student'].id} student", f"contact {world['contact'].id}",
                 f"schedule {world['sched_student'].id}", f"invoice {world['draft'].id}",
                 f"Duplicate teacher {world['duplicate'].id}"):
        assert line in out
    _refresh(world['student'], world['contact'], world['sched_student'], world['sched_kept'])
    assert world['student'].is_active and world['student'].email == 'realparent@example.com'
    assert world['contact'].email == 'realparent@example.com'
    assert world['sched_student'].is_active and world['sched_kept'].is_active
    assert PreBillingInvoice.objects.filter(pk=world['draft'].pk).exists()
    assert User.objects.filter(pk=world['duplicate'].pk).exists()


@pytest.mark.django_db
def test_apply_neutralizes_test_rows_and_leaves_real_rows(world, tmp_path):
    pre = tmp_path / 'pre.json'
    old_refresh = RefreshToken.for_user(world['student'])

    _run('--apply', '--pre-state', str(pre))

    s, s2, t = world['student'], world['student2'], world['test_teacher']
    _refresh(s, s2, t, world['contact'], world['sched_student'], world['sched_kept'], world['kept'])
    for u in (s, s2, t):
        assert u.email == f'test+{u.id}@{TEST_DOMAIN}'
        assert u.is_active is False
    assert BlacklistedToken.objects.filter(token__jti=old_refresh['jti']).exists()
    assert world['contact'].email == f'contact+{s.id}@{TEST_DOMAIN}'
    assert world['sched_student'].is_active is False
    assert world['sched_student'].end_date == timezone.localdate()
    assert world['sched_kept'].is_active is False
    assert not PreBillingInvoice.objects.filter(pk=world['draft'].pk).exists()
    assert not InvoiceSendItem.objects.filter(invoice_id=world['draft'].pk).exists()
    # kept teacher
    assert world['kept'].is_active and world['kept'].email == 'owner.login@example.com'
    # empty duplicate hard-deleted
    assert not User.objects.filter(pk=world['duplicate'].pk).exists()
    # untouched: paid invoice, lessons, batches, credit rows, real accounts
    _refresh(world['paid'], world['account'], world['real_student'], world['real_teacher'],
             world['sched_real'], world['real_draft'])
    assert world['paid'].status == 'paid'
    assert world['account'].balance == Decimal('103.00')
    assert CreditTransaction.objects.filter(pk=world['credit'].pk).exists()
    assert Lesson.objects.filter(pk=world['lesson'].pk).exists()
    assert MonthlyInvoiceBatch.objects.filter(pk=world['batch'].pk).exists()
    assert world['real_student'].is_active and world['real_student'].email == 'ray@example.com'
    assert world['real_teacher'].is_active and world['sched_real'].is_active
    assert world['real_draft'].status == 'draft'
    # history rows written for the soft changes
    assert s.history.filter(email=f'test+{s.id}@{TEST_DOMAIN}').exists()
    assert pre.exists()


@pytest.mark.django_db
def test_second_apply_is_noop(world, tmp_path):
    _run('--apply', '--pre-state', str(tmp_path / 'a.json'))
    history_before = User.objects.get(pk=world['student'].pk).history.count()
    schedule_history_before = world['sched_kept'].history.count()

    out = _run('--apply', '--pre-state', str(tmp_path / 'b.json'))

    assert 'Nothing to do' in out
    assert User.objects.get(pk=world['student'].pk).history.count() == history_before
    assert world['sched_kept'].history.count() == schedule_history_before
    assert not (tmp_path / 'b.json').exists()


@pytest.mark.django_db
def test_snapshot_mismatch_exits_nonzero_and_writes_nothing(world, tmp_path):
    world['student'].first_name = 'Someone Else'
    world['student'].save(update_fields=['first_name'])

    with pytest.raises(CommandError, match='Snapshot mismatch'):
        _run('--apply', '--pre-state', str(tmp_path / 'p.json'))

    _refresh(world['student2'], world['contact'], world['sched_kept'])
    assert world['student2'].is_active and world['student2'].email == 'matt.test@example.com'
    assert world['contact'].email == 'realparent@example.com'
    assert world['sched_kept'].is_active
    assert PreBillingInvoice.objects.filter(pk=world['draft'].pk).exists()
    assert User.objects.filter(pk=world['duplicate'].pk).exists()
    assert not (tmp_path / 'p.json').exists()


@pytest.mark.django_db
def test_duplicate_teacher_with_rows_is_neutralized_not_deleted(world, tmp_path):
    _schedule(world['kept'].school, world['duplicate'], world['real_student'])

    out = _run('--apply', '--pre-state', str(tmp_path / 'p.json'))

    dup = User.objects.get(pk=world['duplicate'].pk)
    assert dup.is_active is False
    assert dup.email == f'test+{dup.id}@{TEST_DOMAIN}'
    assert 'neutralized, not deleted' in out


@pytest.mark.django_db
def test_kept_teacher_check_rolls_back_when_it_would_be_left_inactive(world, tmp_path, monkeypatch):
    # Kept teacher listed as a test teacher by mistake → its own assertion fails → rollback.
    monkeypatch.setattr(cmd, 'TEST_TEACHER_IDS', [world['test_teacher'].id, world['kept'].id])

    with pytest.raises(CommandError, match='Kept teacher'):
        _run('--apply', '--pre-state', str(tmp_path / 'p.json'))

    _refresh(world['student'], world['kept'], world['contact'])
    assert world['student'].is_active and world['student'].email == 'realparent@example.com'
    assert world['kept'].is_active and world['kept'].email == 'owner.login@example.com'
    assert world['contact'].email == 'realparent@example.com'
    assert PreBillingInvoice.objects.filter(pk=world['draft'].pk).exists()


@pytest.mark.django_db
def test_revert_restores_users_contacts_schedules_and_duplicate(world, tmp_path):
    pre = tmp_path / 'pre.json'
    _run('--apply', '--pre-state', str(pre))

    out = _run('--revert', str(pre))

    s, s2, t = world['student'], world['student2'], world['test_teacher']
    _refresh(s, s2, t, world['contact'], world['sched_student'], world['sched_kept'])
    assert (s.email, s.is_active) == ('realparent@example.com', True)
    assert (s2.email, s2.is_active) == ('matt.test@example.com', True)
    assert (t.email, t.is_active) == ('asd@example.com', True)
    assert world['contact'].email == 'realparent@example.com'
    assert world['sched_student'].is_active and world['sched_student'].end_date is None
    assert world['sched_kept'].is_active
    dup = User.objects.get(pk=world['duplicate'].pk)
    assert (dup.email, dup.first_name, dup.user_type, dup.is_active) == ('wmk@example.com', 'William', 'teacher', True)
    assert 'not restored' in out and str(world['draft'].pk) in out
    assert not PreBillingInvoice.objects.filter(pk=world['draft'].pk).exists()


def test_every_real_listed_id_has_a_snapshot_row():
    """Data guard: the prod id lists and EXPECTED must agree before this ships."""
    listed = set(cmd.TEST_STUDENT_IDS + cmd.TEST_TEACHER_IDS + [cmd.KEEP_TEACHER_ID, cmd.DUPLICATE_TEACHER_ID])
    assert len(cmd.TEST_STUDENT_IDS) == 17
    assert len(cmd.TEST_TEACHER_IDS) == 3
    assert set(cmd.EXPECTED) == listed
    for user_id, (first, last, email) in cmd.EXPECTED.items():
        assert email and '@' in email, user_id
        assert not email.endswith(f'@{TEST_DOMAIN}'), user_id
