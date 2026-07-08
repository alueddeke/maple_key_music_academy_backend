"""Repair legacy RecurringLessonsSchedule rows that stored duration in MINUTES.

The schedule form has always submitted duration in decimal HOURS, but a
handful of early rows (pre-form, school 1) were created with minute values
(e.g. 60 meaning "60 minutes" stored as 60.00 HOURS). Those rows inflate the
Analytics scheduled-MRR figure ~60× and would generate absurd lesson hours.

Heuristic: no real lesson is >= 8 hours, and every legacy bad value is a
known minute option (15/30/45/60/75/90/105/120) — so any duration >= 8 is
treated as minutes and divided by 60.

Rates are NOT touched (they are locked per-hour rates; only the hours were
wrong). django-simple-history records each change with this command's run.

Dry-run by default. Usage:
    python manage.py fix_legacy_schedule_durations           # report only
    python manage.py fix_legacy_schedule_durations --apply   # write changes
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from billing.models import RecurringLessonsSchedule

# Any duration at or above this is impossible as hours → interpret as minutes
MINUTES_THRESHOLD = Decimal('8')


class Command(BaseCommand):
    help = (
        "Convert legacy schedule durations stored as minutes (>= 8) to hours. "
        "Dry-run unless --apply is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Write the corrections (default is a dry-run report)',
        )

    def handle(self, *args, **options):
        suspects = RecurringLessonsSchedule.objects.filter(
            duration__gte=MINUTES_THRESHOLD
        ).select_related('teacher', 'student').order_by('id')

        if not suspects.exists():
            self.stdout.write(self.style.SUCCESS(
                'No legacy minute-valued durations found — nothing to do.'
            ))
            return

        for schedule in suspects:
            corrected = (Decimal(str(schedule.duration)) / 60).quantize(
                Decimal('0.01')
            )
            self.stdout.write(
                f"Schedule {schedule.id}: {schedule.teacher.email} → "
                f"{schedule.student.email} | {schedule.duration}h → {corrected}h"
                f" ({'active' if schedule.is_active else 'inactive'})"
            )
            if options['apply']:
                schedule.duration = corrected
                schedule.save(update_fields=['duration'])

        count = suspects.count() if not options['apply'] else 'DONE — corrected'
        if options['apply']:
            self.stdout.write(self.style.SUCCESS(
                'Corrections applied. History records written.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN — {count} row(s) would change. Re-run with --apply.'
            ))
