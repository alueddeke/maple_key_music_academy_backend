"""
Neutralize the production test accounts (MAP-218).

Closed id lists only — no pattern matching on names or domains. Confirmed by
the owner on 2026-09-21 from a read-only prod analysis. Any real person's
record is out of scope; an ambiguous account is left alone.

Per test user, in one transaction (saves go through the model so history
rows are written):
  - email -> test+{id}@maplekeytest.com, is_active False, tokens revoked
  - every BillableContact of a test student -> contact+{student_id}@maplekeytest.com
  - every active RecurringLessonsSchedule whose student or teacher is listed
    (incl. the kept teacher's) -> is_active False, end_date today
  - every draft PreBillingInvoice of a test student -> deleted (drafts have
    no Helcim side; their dead InvoiceSendItem rows go with them)
  - the duplicate teacher -> hard delete() only if it has no lessons,
    schedules, invoices or batches; otherwise neutralized like the others
  - the kept teacher -> asserted only: active, email unchanged, no active
    schedules after the run
Paid invoices, lessons, payroll batches and credit rows are never touched.

Drift guard: every listed id must still carry the name/email snapshot in
EXPECTED (or already be neutralized) or the command exits 1 without writing.

Rollback (owner request 2026-09-22): --apply writes a pre-state JSON of every
row it changes before touching anything; --revert <file> restores users,
contacts and schedules and re-creates the duplicate teacher if it was
deleted. Deleted drafts are regenerable and are not restored.

Usage:
  python manage.py neutralize_test_accounts                   # dry run (default)
  python manage.py neutralize_test_accounts --apply [--pre-state PATH]
  python manage.py neutralize_test_accounts --revert PATH
"""

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from billing.models import (
    BillableContact,
    Lesson,
    MonthlyInvoiceBatch,
    PreBillingInvoice,
    RecurringLessonsSchedule,
    User,
)
from custom_auth.authentication import revoke_user_tokens

TEST_DOMAIN = 'maplekeytest.com'

TEST_STUDENT_IDS = [60, 61, 66, 81, 82, 83, 84, 85, 86, 109, 117, 118, 124, 125, 126, 133, 149]
TEST_TEACHER_IDS = [11, 120, 123]
KEEP_TEACHER_ID = 3          # owner's own test login: stays active, email unchanged
DUPLICATE_TEACHER_ID = 108   # same person as teacher 105; delete only if empty

# Prod snapshot (first_name, last_name, email) per listed id — drift guard.
# Filled from the owner-run read-only query recorded on MAP-218.
EXPECTED = {
    # read-only prod query 2026-09-22 (owner-run), recorded on MAP-218
    3: ('Toni Teacher', 'Test', 'a.lueddeke@hotmail.com'),
    11: ('Matt', 'Morgan', 'asd@gmail.com'),
    60: ('Antoni', 'Lueddeke', 'student_1_noemail@maplekeymusic.internal'),
    61: ('Antonii', 'Lueddeke', 'student_test@gmail.com'),
    66: ('Joe', 'lue', 'student_2_noemail@maplekeymusic.internal'),
    81: ('test5', 'test55', 'test5@gmail.com'),
    82: ('joey', '', 'joey@temp.com'),
    83: ('bill', '', 'bill@temp.com'),
    84: ('matt', '', 'matt@temp.com'),
    85: ('test6', 'test66', 'test66@gmail.com'),
    86: ('Antoni', 'Lueddeke', 'antoni.lueddeke@temp.com'),
    108: ('William', 'Kervin', 'wmkervin@gmail.com'),
    109: ('April', 'Tester', 'asdsddd@gmail.com'),
    117: ('Bill Test', 'Student', 'billy.kervin154@gmail.com'),
    118: ('Bill Test Student', '2', 'mercedesturnersmith@gmail.com'),
    120: ('Test', 'Teacher', 'testteacher@maplekeymusic.com'),
    123: ('Maple Key', 'Test User', 'maplekeyteacher@gmail.com'),
    124: ('John', 'Smith', 'johnsmith@hotmail.com'),
    125: ('James', 'Morgan', 'jamesmorgan@live.ca'),
    126: ('May Test', 'Student', 'maytest@gmail.com'),
    133: ('june', 'tester', 'junetest@gmail.com'),
    149: ('matt', 'test morgan', 'guitarmatt@live.ca'),
}

USER_FIELDS = ('email', 'is_active')
CONTACT_FIELDS = ('email',)
SCHEDULE_FIELDS = ('is_active', 'end_date')
DUPLICATE_TEACHER_FIELDS = (
    'email', 'first_name', 'last_name', 'user_type', 'school_id', 'is_active',
    'is_approved', 'is_staff', 'password', 'hourly_rate', 'phone_number',
    'address', 'oauth_provider', 'date_joined',
)


def neutralized_email(user_id):
    return f'test+{user_id}@{TEST_DOMAIN}'


def neutralized_contact_email(student_id):
    return f'contact+{student_id}@{TEST_DOMAIN}'


def _all_listed_ids():
    return TEST_STUDENT_IDS + TEST_TEACHER_IDS + [KEEP_TEACHER_ID, DUPLICATE_TEACHER_ID]


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


class Command(BaseCommand):
    help = 'Neutralize the closed list of production test accounts (dry run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write the changes (default is dry run).')
        parser.add_argument('--pre-state', default=None,
                            help='Where --apply writes the pre-state JSON (default /tmp/neutralize-pre-state-<utc>.json).')
        parser.add_argument('--revert', default=None, metavar='PATH',
                            help='Restore users/contacts/schedules from a pre-state JSON written by --apply.')

    # ------------------------------------------------------------------ main
    def handle(self, *args, **options):
        if options['revert']:
            return self._revert(options['revert'])

        self._check_snapshot()
        plan = self._build_plan()
        self._print_plan(plan)

        if not options['apply']:
            self.stdout.write(self.style.WARNING('Dry run — nothing written. Re-run with --apply.'))
            return

        if not plan['has_work']:
            self.stdout.write(self.style.SUCCESS('Nothing to do — already neutralized.'))
            return

        pre_state_path = options['pre_state'] or (
            f'/tmp/neutralize-pre-state-{timezone.now():%Y%m%d-%H%M%S}.json'
        )
        with open(pre_state_path, 'w') as fh:
            json.dump(plan['pre_state'], fh, indent=2, default=_json_default)
        self.stdout.write(f'Pre-state written: {pre_state_path}')

        with transaction.atomic():
            self._apply(plan)
            self._assert_kept_teacher()
        self.stdout.write(self.style.SUCCESS('Applied.'))

    # ----------------------------------------------------------- drift guard
    def _check_snapshot(self):
        problems = []
        users = User.objects.in_bulk(_all_listed_ids())
        for user_id in _all_listed_ids():
            expected = EXPECTED.get(user_id)
            if expected is None:
                problems.append(f'id {user_id}: no snapshot in EXPECTED')
                continue
            user = users.get(user_id)
            if user is None:
                if user_id == DUPLICATE_TEACHER_ID:
                    continue  # already deleted by a previous --apply
                problems.append(f'id {user_id}: no such user')
                continue
            first, last, email = expected
            actual = (user.first_name, user.last_name, user.email.lower())
            already_done = user.email.lower() == neutralized_email(user_id) and (first, last) == actual[:2]
            if actual != (first, last, email.lower()) and not already_done:
                problems.append(
                    f'id {user_id}: expected {expected!r}, found {actual!r}'
                )
        if problems:
            raise CommandError(
                'Snapshot mismatch — nothing written:\n  ' + '\n  '.join(problems)
            )

    # ----------------------------------------------------------------- plan
    def _build_plan(self):
        today = timezone.localdate()
        users = User.objects.in_bulk(_all_listed_ids())
        plan = {
            'today': today,
            'users': [],          # (user, new_email)
            'contacts': [],       # (contact, new_email)
            'schedules': [],      # schedule
            'drafts': [],         # invoice
            'duplicate': None,    # ('delete' | 'neutralize', user, counts)
            'pre_state': {'users': [], 'contacts': [], 'schedules': [], 'drafts': [],
                          'duplicate_teacher': None, 'today': today},
        }

        for user_id in TEST_STUDENT_IDS + TEST_TEACHER_IDS:
            user = users[user_id]
            if user.email.lower() != neutralized_email(user_id) or user.is_active:
                plan['users'].append((user, neutralized_email(user_id)))
                plan['pre_state']['users'].append(
                    {'id': user.id, **{f: getattr(user, f) for f in USER_FIELDS}}
                )

        for contact in BillableContact.objects.filter(student_id__in=TEST_STUDENT_IDS).order_by('id'):
            new_email = neutralized_contact_email(contact.student_id)
            if contact.email.lower() != new_email:
                plan['contacts'].append((contact, new_email))
                plan['pre_state']['contacts'].append(
                    {'id': contact.id, **{f: getattr(contact, f) for f in CONTACT_FIELDS}}
                )

        teacher_ids = TEST_TEACHER_IDS + [KEEP_TEACHER_ID, DUPLICATE_TEACHER_ID]
        for schedule in (
            RecurringLessonsSchedule.objects
            .filter(is_active=True)
            .filter(Q(student_id__in=TEST_STUDENT_IDS) | Q(teacher_id__in=teacher_ids))
            .order_by('id')
        ):
            plan['schedules'].append(schedule)
            plan['pre_state']['schedules'].append(
                {'id': schedule.id, **{f: getattr(schedule, f) for f in SCHEDULE_FIELDS}}
            )

        for invoice in (
            PreBillingInvoice.objects
            .filter(status='draft', student_id__in=TEST_STUDENT_IDS)
            .order_by('id')
        ):
            plan['drafts'].append(invoice)
            plan['pre_state']['drafts'].append({
                'id': invoice.id, 'student_id': invoice.student_id,
                'amount': invoice.amount, 'period_start': invoice.period_start,
                'period_end': invoice.period_end,
                'send_item_ids': list(invoice.send_items.values_list('id', flat=True)),
            })

        duplicate = users.get(DUPLICATE_TEACHER_ID)
        if duplicate is not None:
            counts = {
                'lessons': Lesson.objects.filter(teacher=duplicate).count(),
                'schedules': RecurringLessonsSchedule.objects.filter(teacher=duplicate).count(),
                'invoices': PreBillingInvoice.objects.filter(student=duplicate).count(),
                'batches': MonthlyInvoiceBatch.objects.filter(teacher=duplicate).count(),
            }
            if any(counts.values()):
                action = 'neutralize'
                if duplicate.email.lower() == neutralized_email(duplicate.id) and not duplicate.is_active:
                    action = None
            else:
                action = 'delete'
            if action:
                plan['duplicate'] = (action, duplicate, counts)
                plan['pre_state']['duplicate_teacher'] = {
                    'id': duplicate.id, 'action': action,
                    **{f: getattr(duplicate, f) for f in DUPLICATE_TEACHER_FIELDS},
                }

        plan['has_work'] = any([
            plan['users'], plan['contacts'], plan['schedules'], plan['drafts'], plan['duplicate'],
        ])
        return plan

    def _print_plan(self, plan):
        w = self.stdout.write
        w(f"Users to neutralize ({len(plan['users'])}):")
        for user, new_email in plan['users']:
            w(f"  {user.id} {user.user_type} {user.first_name} {user.last_name} "
              f"{user.email} -> {new_email}, is_active False, tokens revoked")
        w(f"Billable contacts to rewrite ({len(plan['contacts'])}):")
        for contact, new_email in plan['contacts']:
            w(f"  contact {contact.id} (student {contact.student_id}) {contact.email} -> {new_email}")
        w(f"Schedules to end ({len(plan['schedules'])}), end_date {plan['today']}:")
        for schedule in plan['schedules']:
            w(f"  schedule {schedule.id} student {schedule.student_id} teacher {schedule.teacher_id}")
        w(f"Draft invoices to delete ({len(plan['drafts'])}):")
        for invoice in plan['drafts']:
            w(f"  invoice {invoice.id} student {invoice.student_id} amount {invoice.amount}")
        if plan['duplicate']:
            action, duplicate, counts = plan['duplicate']
            w(f"Duplicate teacher {duplicate.id} {duplicate.email}: {action} (rows: {counts})")
        else:
            w(f"Duplicate teacher {DUPLICATE_TEACHER_ID}: nothing to do")
        w(f"Kept teacher {KEEP_TEACHER_ID}: asserted only (active, email unchanged, no active schedules)")

    # ---------------------------------------------------------------- apply
    def _apply(self, plan):
        for user, new_email in plan['users']:
            self._neutralize_user(user, new_email)
        for contact, new_email in plan['contacts']:
            contact.email = new_email
            contact.save(update_fields=['email'])
        for schedule in plan['schedules']:
            schedule.is_active = False
            schedule.end_date = plan['today']
            schedule.save(update_fields=['is_active', 'end_date'])
        for invoice in plan['drafts']:
            # InvoiceSendItem.invoice is PROTECT — the dead attempts of a
            # draft go with it (owner ruling 2026-09-22).
            invoice.send_items.all().delete()
            invoice_id = invoice.id  # delete() clears the pk
            invoice.delete()
            self.stdout.write(f'Deleted draft invoice {invoice_id}')
        if plan['duplicate']:
            action, duplicate, counts = plan['duplicate']
            if action == 'delete':
                duplicate.delete()
                self.stdout.write(f'Deleted duplicate teacher {duplicate.id}')
            else:
                self._neutralize_user(duplicate, neutralized_email(duplicate.id))
                self.stdout.write(
                    f'Duplicate teacher {duplicate.id} has rows {counts} — neutralized, not deleted'
                )

    def _neutralize_user(self, user, new_email):
        user.email = new_email
        user.is_active = False
        user.save(update_fields=['email', 'is_active'])
        revoke_user_tokens(user)

    def _assert_kept_teacher(self):
        kept = User.objects.get(pk=KEEP_TEACHER_ID)
        expected_email = EXPECTED[KEEP_TEACHER_ID][2]
        active_schedules = RecurringLessonsSchedule.objects.filter(
            is_active=True,
        ).filter(Q(teacher=kept) | Q(student=kept)).count()
        if not kept.is_active or kept.email.lower() != expected_email.lower() or active_schedules:
            raise CommandError(
                f'Kept teacher {KEEP_TEACHER_ID} check failed: is_active={kept.is_active} '
                f'email={kept.email} active_schedules={active_schedules} — rolled back'
            )
        self.stdout.write(f'Kept teacher {KEEP_TEACHER_ID}: active, email unchanged, 0 active schedules')

    # --------------------------------------------------------------- revert
    def _revert(self, path):
        with open(path) as fh:
            state = json.load(fh)
        with transaction.atomic():
            for row in state['users']:
                user = User.objects.get(pk=row['id'])
                for field in USER_FIELDS:
                    setattr(user, field, row[field])
                user.save(update_fields=list(USER_FIELDS))
                self.stdout.write(f"Restored user {user.id} {user.email} is_active={user.is_active}")
            for row in state['contacts']:
                contact = BillableContact.objects.get(pk=row['id'])
                contact.email = row['email']
                contact.save(update_fields=['email'])
                self.stdout.write(f"Restored contact {contact.id} {contact.email}")
            for row in state['schedules']:
                schedule = RecurringLessonsSchedule.objects.get(pk=row['id'])
                schedule.is_active = row['is_active']
                schedule.end_date = date.fromisoformat(row['end_date']) if row['end_date'] else None
                schedule.save(update_fields=['is_active', 'end_date'])
                self.stdout.write(f"Restored schedule {schedule.id} is_active={schedule.is_active}")
            dup = state.get('duplicate_teacher')
            if dup:
                if dup['action'] == 'delete' and not User.objects.filter(pk=dup['id']).exists():
                    fields = {f: dup[f] for f in DUPLICATE_TEACHER_FIELDS if f != 'date_joined'}
                    user = User(id=dup['id'], **fields)
                    user.save()
                    User.objects.filter(pk=user.pk).update(date_joined=dup['date_joined'])
                    self.stdout.write(f"Re-created duplicate teacher {user.id} {user.email}")
                elif dup['action'] == 'neutralize':
                    user = User.objects.get(pk=dup['id'])
                    user.email = dup['email']
                    user.is_active = dup['is_active']
                    user.save(update_fields=['email', 'is_active'])
                    self.stdout.write(f"Restored duplicate teacher {user.id} {user.email}")
            if state['drafts']:
                self.stdout.write(self.style.WARNING(
                    f"{len(state['drafts'])} deleted draft invoice(s) not restored "
                    f"(ids {[d['id'] for d in state['drafts']]}) — regenerate them"
                ))
        self.stdout.write(self.style.SUCCESS('Reverted.'))
