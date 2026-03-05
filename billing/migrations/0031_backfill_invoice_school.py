# Generated manually for Phase 3 - Multi-tenancy migration
# Migration 0031: Backfill Invoice.school from teacher or student's school

from django.db import migrations


def backfill_invoice_school(apps, schema_editor):
    """
    Assign each invoice to the appropriate school:
    - teacher_payment invoices → teacher's school
    - student_billing invoices → student's school
    Idempotent: Safe to run multiple times.
    """
    Invoice = apps.get_model('billing', 'Invoice')
    School = apps.get_model('billing', 'School')

    # Verify default school exists
    try:
        default_school = School.objects.get(id=1)
    except School.DoesNotExist:
        raise Exception("Default school (id=1) must exist. Run migration 0027 first.")

    # Get invoices without school
    invoices_without_school = Invoice.objects.filter(school__isnull=True).select_related('teacher', 'student')
    count = invoices_without_school.count()

    if count == 0:
        print("All invoices already have school assigned, skipping backfill")
        return

    print(f"Backfilling {count} invoices with appropriate school")

    # Process each invoice
    updated = 0
    teacher_invoices = 0
    student_invoices = 0
    default_assigned = 0

    for invoice in invoices_without_school:
        if invoice.invoice_type == 'teacher_payment':
            # Teacher payment: use teacher's school
            if invoice.teacher and invoice.teacher.school_id:
                invoice.school_id = invoice.teacher.school_id
                teacher_invoices += 1
            else:
                invoice.school_id = default_school.id
                default_assigned += 1
        else:  # student_billing
            # Student billing: use student's school
            if invoice.student and invoice.student.school_id:
                invoice.school_id = invoice.student.school_id
                student_invoices += 1
            else:
                invoice.school_id = default_school.id
                default_assigned += 1

        updated += 1

    # Bulk update for efficiency
    Invoice.objects.bulk_update(invoices_without_school, ['school'])

    print(f"✓ {updated} invoices assigned to school:")
    print(f"  - {teacher_invoices} teacher payment invoices")
    print(f"  - {student_invoices} student billing invoices")
    if default_assigned > 0:
        print(f"  - {default_assigned} invoices assigned to default school (user had no school)")

    # Verification
    orphaned = Invoice.objects.filter(school__isnull=True).count()
    if orphaned > 0:
        raise Exception(f"ERROR: {orphaned} invoices still have no school after backfill!")

    print("✓ Verification passed: All invoices have school assigned")


def reverse_backfill_invoice_school(apps, schema_editor):
    """
    Reverse migration: Clear school FK for all invoices.
    """
    Invoice = apps.get_model('billing', 'Invoice')

    invoices_with_school = Invoice.objects.filter(school__isnull=False)
    count = invoices_with_school.count()

    if count == 0:
        print("No invoices have school assigned, nothing to reverse")
        return

    print(f"Clearing school assignment for {count} invoices")
    invoices_with_school.update(school=None)
    print(f"✓ {count} invoices cleared")


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0030_backfill_lesson_school'),
    ]

    operations = [
        migrations.RunPython(
            backfill_invoice_school,
            reverse_code=reverse_backfill_invoice_school
        ),
    ]
