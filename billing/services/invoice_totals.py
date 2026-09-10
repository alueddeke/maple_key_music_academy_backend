"""
Invoice totals — the single writer of Invoice.total_amount / payment_balance.

Invoice.save() never recomputes money (MAP-183). Every site that mutates the
Invoice.lessons M2M calls recalculate() explicitly afterwards; status-only
edits (mark as paid, reference number) go through a plain save() and leave
the monetary fields untouched. Payroll invoices carry no lessons and are
priced at generation — they must never be passed through recalculate().
"""


def recalculate(invoice):
    """Recompute both monetary fields from the invoice's lessons and persist them.

    Uses Invoice.calculate_payment_balance() — the one per-lesson pricing rule
    (teacher_rate for teacher_payment, student_rate for student_billing).
    Returns the new total.
    """
    total = invoice.calculate_payment_balance()
    invoice.total_amount = total
    invoice.payment_balance = total
    invoice.save(update_fields=['total_amount', 'payment_balance'])
    return total
