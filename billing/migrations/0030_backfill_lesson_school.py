# Generated manually for Phase 3 - Multi-tenancy migration
# Migration 0030: Backfill Lesson.school from teacher's school

from django.db import migrations


def backfill_lesson_school(apps, schema_editor):
    """
    Assign each lesson to the teacher's school.
    Idempotent: Safe to run multiple times.
    """
    Lesson = apps.get_model('billing', 'Lesson')
    School = apps.get_model('billing', 'School')

    # Verify default school exists
    try:
        default_school = School.objects.get(id=1)
    except School.DoesNotExist:
        raise Exception("Default school (id=1) must exist. Run migration 0027 first.")

    # Get lessons without school
    lessons_without_school = Lesson.objects.filter(school__isnull=True).select_related('teacher')
    count = lessons_without_school.count()

    if count == 0:
        print("All lessons already have school assigned, skipping backfill")
        return

    print(f"Backfilling {count} lessons with teacher's school")

    # Process each lesson
    updated = 0
    lessons_needing_default = []

    for lesson in lessons_without_school:
        if lesson.teacher and lesson.teacher.school_id:
            # Assign to teacher's school
            lesson.school_id = lesson.teacher.school_id
            lessons_needing_default.append(lesson)
            updated += 1
        else:
            # Teacher has no school, use default
            lesson.school_id = default_school.id
            updated += 1

    # Bulk update for efficiency
    Lesson.objects.bulk_update(lessons_without_school, ['school'])

    print(f"✓ {updated} lessons assigned to school")
    if lessons_needing_default:
        print(f"  - {len(lessons_needing_default)} lessons assigned to default school (teacher had no school)")

    # Verification
    orphaned = Lesson.objects.filter(school__isnull=True).count()
    if orphaned > 0:
        raise Exception(f"ERROR: {orphaned} lessons still have no school after backfill!")

    print("✓ Verification passed: All lessons have school assigned")


def reverse_backfill_lesson_school(apps, schema_editor):
    """
    Reverse migration: Clear school FK for all lessons.
    """
    Lesson = apps.get_model('billing', 'Lesson')

    lessons_with_school = Lesson.objects.filter(school__isnull=False)
    count = lessons_with_school.count()

    if count == 0:
        print("No lessons have school assigned, nothing to reverse")
        return

    print(f"Clearing school assignment for {count} lessons")
    lessons_with_school.update(school=None)
    print(f"✓ {count} lessons cleared")


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0029_backfill_user_school'),
    ]

    operations = [
        migrations.RunPython(
            backfill_lesson_school,
            reverse_code=reverse_backfill_lesson_school
        ),
    ]
