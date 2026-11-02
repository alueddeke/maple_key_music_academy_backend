"""
Teacher pay for a billing period — the one rule both the Analytics trend and
the management dashboard read (MAP-314).

A payroll Invoice (invoice_type='teacher_payment') is created per approved
batch only when management clicks "Generate Teacher Invoice", so summing
invoices alone undercounts every month until the last batch's payroll has been
generated — Billed (Student Billing invoices, written at approval) was complete
while Teacher Pay was partial, and Margin was inflated by the gap.

Rule: every APPROVED batch in (school, year, month) counts.
  - batch.invoice set     → invoice.total_amount          ("generated")
  - no invoice yet        → Σ item.calculate_teacher_payment()  ("pending")
Draft / submitted / rejected batches contribute nothing.
"""

from decimal import Decimal, ROUND_HALF_UP

from billing.models import MonthlyInvoiceBatch


def approved_teacher_pay(school, year, month, *, exclude=None):
    """Return {'total', 'generated', 'pending'} as Decimals for the period.

    `exclude` is an optional callable applied to the batch queryset (the
    analytics test-data filter on `teacher__email`); it must return a queryset.
    """
    batches = MonthlyInvoiceBatch.objects.filter(
        school=school, year=year, month=month, status='approved',
    )
    if exclude is not None:
        batches = exclude(batches)
    batches = batches.select_related('invoice').prefetch_related('lesson_items')

    generated = Decimal('0.00')
    pending = Decimal('0.00')
    for batch in batches:
        if batch.invoice_id is not None:
            generated += batch.invoice.total_amount or Decimal('0.00')
        else:
            pending += sum(
                (item.calculate_teacher_payment() for item in batch.lesson_items.all()),
                Decimal('0.00'),
            )
    # Money on the wire is 2dp. A per-lesson pay is rate (2dp) × duration
    # (2dp) = 4dp, and str() of that ("4010.0000") fails the frontend's strict
    # money schema and blanks the dashboard (e2e red on develop, 2026-11-02).
    pending = pending.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {'total': generated + pending, 'generated': generated, 'pending': pending}
