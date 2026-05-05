"""
Fix duration values that were stored as minutes instead of hours.

This command identifies BatchLessonItem records with suspiciously high duration values
(likely stored as minutes instead of hours) and converts them to hours.
"""
from django.core.management.base import BaseCommand
from billing.models import BatchLessonItem
from decimal import Decimal


class Command(BaseCommand):
    help = 'Fix duration values stored as minutes instead of hours in BatchLessonItem'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes',
        )
        parser.add_argument(
            '--threshold',
            type=int,
            default=10,
            help='Duration threshold (hours) - values above this are likely minutes (default: 10)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        threshold = Decimal(str(options['threshold']))

        self.stdout.write(self.style.NOTICE(
            f"\nSearching for BatchLessonItems with duration > {threshold} hours (likely stored as minutes)..."
        ))

        # Find lessons with suspiciously high duration (likely minutes stored as hours)
        bad_lessons = BatchLessonItem.objects.filter(duration__gt=threshold)

        if not bad_lessons.exists():
            self.stdout.write(self.style.SUCCESS(
                "\n✅ No suspicious duration values found. All lessons appear correct."
            ))
            return

        self.stdout.write(self.style.WARNING(
            f"\nFound {bad_lessons.count()} lesson(s) with suspicious duration values:\n"
        ))

        fixes = []
        for lesson in bad_lessons:
            old_duration = lesson.duration
            new_duration = old_duration / 60  # Convert minutes to hours

            self.stdout.write(
                f"  ID: {lesson.id} | {lesson.student.get_full_name()} | "
                f"{lesson.scheduled_date} {lesson.start_time} | "
                f"{old_duration} hrs → {new_duration} hrs"
            )

            fixes.append({
                'lesson': lesson,
                'old': old_duration,
                'new': new_duration
            })

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\n🔍 DRY RUN - No changes made. Remove --dry-run to apply fixes."
            ))
            return

        # Apply fixes
        self.stdout.write(self.style.NOTICE("\nApplying fixes..."))
        for fix in fixes:
            lesson = fix['lesson']
            lesson.duration = fix['new']
            lesson.save(update_fields=['duration'])

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Successfully fixed {len(fixes)} lesson(s)."
        ))
        self.stdout.write(self.style.SUCCESS(
            "Duration values have been converted from minutes to hours."
        ))
