"""
Single-invoice send pipeline for pre-billing (Helcim invoice + payment email).

Extracted verbatim from views/pre_billing.py (batch-queue wave phase 1) so the
send-run worker and the HTTP views share one implementation. Behavior contract
unchanged:
- All HelcimClient HTTP calls stay OUTSIDE any transaction.atomic() block
  (STATE.md / T-19-03-06) — wrapping them orphans Helcim invoices on rollback.
- The draft -> sending conditional UPDATE is the double-send lock; exactly one
  caller wins, and a failed send releases the claim.
"""
import logging
from decimal import Decimal

from django.db import transaction

from ..models import (
    BillableContact,
    PreBillingInvoice,
    RecurringLessonsSchedule,
    StudentCreditAccount,
)
from .helcim_client import HelcimClient, HelcimAPIError, payment_page_url
from .email_service import PreBillingEmailService
from billing.metrics import invoices_sent_total

logger = logging.getLogger(__name__)


class InvoiceSendConflict(Exception):
    """Raised when an invoice is not in a sendable state (double-send guard)."""



def projected_items(invoice):
    """
    Project lesson line items for a bill-ahead invoice from the student's
    active recurring schedules — the same sourcing generate uses (D-08).

    Future-period invoices have an EMPTY lessons M2M by design (Lesson rows
    only exist after batch approval), so display, send, and email must all
    derive dates from the schedule projection instead.
    """
    items = []
    excluded = set(invoice.excluded_dates or [])
    schedules = RecurringLessonsSchedule.objects.filter(
        student=invoice.student,
        school=invoice.school,
        is_active=True,
    ).select_related('teacher')
    for sched in schedules:
        for d in sched.generate_lessons_for_month(
            invoice.period_start.year, invoice.period_start.month
        ):
            if d.isoformat() in excluded:
                continue
            items.append({
                'date': d,
                'rate': Decimal(str(sched.student_rate)),
                'duration': Decimal(str(sched.duration)),
                'teacher_name': sched.teacher.get_full_name() if sched.teacher else '',
            })
    items.sort(key=lambda item: item['date'])
    return items



def send_single_invoice(invoice, school):
    """
    Send a single draft PreBillingInvoice via Helcim and email.

    All HelcimClient HTTP calls are OUTSIDE any transaction.atomic() block
    per the hard architectural constraint (STATE.md / T-19-03-06).

    Args:
        invoice: PreBillingInvoice instance (status='draft')
        school: School instance (for URL assembly + email sign-off)

    Raises:
        BillableContact.DoesNotExist: if no primary contact found
        HelcimAPIError: if Helcim create_customer or create_invoice fails
    """
    # Re-assert school isolation (belt-and-suspenders; caller already enforces this)
    assert invoice.school_id == school.id, (
        f"School mismatch: invoice.school_id={invoice.school_id} != school.id={school.id}"
    )

    # Lookup primary billing contact — raises DoesNotExist if missing
    contact = BillableContact.objects.select_related('student').get(
        student=invoice.student,
        is_primary=True,
    )

    # Build line items — one per lesson, price = student_rate × duration.
    # Bill-ahead invoices have an empty M2M (Lesson rows only exist after
    # batch approval, D-08) — project dates from the recurring schedules,
    # exactly as generate did.
    lessons = list(invoice.lessons.all().order_by('scheduled_date'))
    projected = projected_items(invoice) if not lessons else []

    # Guard: reject zero-lesson invoices before hitting Helcim
    if not lessons and not projected:
        # status_code=400: validation failure, so the send-run worker never
        # retries it (a bare HelcimAPIError reads as a transient network error).
        raise HelcimAPIError(
            'This invoice has no lesson dates. Add lessons before sending.',
            status_code=400,
        )

    # Schedule-sourced drafts: schedules (or credit) may have changed since
    # the draft was generated — recompute so stored amount, email, and the
    # Helcim page all agree at the moment of sending. Persisted with the
    # final save inside the claim; a failed send never writes it.
    if projected and invoice.status == 'draft':
        gross_projected = sum(
            (item['rate'] * item['duration'] for item in projected),
            Decimal('0.00'),
        ).quantize(Decimal('0.01'))
        try:
            credit_balance = StudentCreditAccount.objects.get(
                student=invoice.student, school=invoice.school
            ).balance
        except StudentCreditAccount.DoesNotExist:
            credit_balance = Decimal('0.00')
        invoice.amount = max(Decimal('0.00'), gross_projected - credit_balance)

    if invoice.amount is None or invoice.amount == 0:
        # status_code=400: validation failure — see the no-lesson guard above.
        raise HelcimAPIError(
            'This invoice has a $0.00 balance. Only invoices with an amount owing can be sent.',
            status_code=400,
        )

    # Atomically claim the invoice (draft → sending) so two concurrent send
    # requests cannot both create Helcim invoices + emails. The conditional
    # UPDATE is the lock; exactly one request wins.
    claimed = PreBillingInvoice.objects.filter(
        pk=invoice.pk, status='draft'
    ).update(status='sending')
    if not claimed:
        raise InvoiceSendConflict(
            'This invoice is already being sent or was already sent.'
        )

    try:
        # Lazy customer creation — OUTSIDE transaction (Helcim HTTP call must not be wrapped)
        if not contact.helcim_customer_id:
            customer_response = HelcimClient(school=school).create_customer(
                contact_name=contact.student.get_full_name()
            )
            customer_id = str(customer_response['id'])
            # Minimal atomic block only for the DB write
            with transaction.atomic():
                BillableContact.objects.filter(pk=contact.pk).update(
                    helcim_customer_id=customer_id
                )
            contact.helcim_customer_id = customer_id

        if projected:
            line_items = [
                {
                    # Helcim requires a sku for line items to appear on the invoice.
                    'sku': f'LESSON-P{i + 1}',
                    'description': f"Lesson on {item['date'].isoformat()}",
                    'quantity': 1,
                    'price': float(item['rate'] * item['duration']),
                }
                for i, item in enumerate(projected)
            ]
        else:
            line_items = [
                {
                    'sku': f'LESSON-{l.pk}',
                    'description': (
                        f"Lesson on {l.scheduled_date.date().strftime('%Y-%m-%d')}"
                        if l.scheduled_date is not None
                        else 'Lesson'
                    ),
                    'quantity': 1,
                    'price': float(
                        Decimal(str(l.student_rate)) * Decimal(str(l.duration))
                    ),
                }
                for l in lessons
            ]

        # invoice.amount is net of wallet credit (generate: max(0, gross − credit)),
        # but line items are gross — without a discount Helcim would charge the
        # parent MORE than the emailed amount. Credit rides as an invoice-level
        # discount (negative line-item prices are rejected by the API), keeping
        # Helcim's amountDue == invoice.amount == emailed amount.
        gross = sum(
            (Decimal(str(li['price'])) for li in line_items),
            Decimal('0.00'),
        ).quantize(Decimal('0.01'))
        credit_applied = gross - invoice.amount
        discount = None
        if credit_applied > Decimal('0.00'):
            discount = {
                'amount': float(credit_applied),
                'details': 'Account credit applied',
            }

        # Create Helcim invoice — OUTSIDE transaction
        helcim_response = HelcimClient(school=school).create_invoice(
            currency='CAD',
            line_items=line_items,
            customer_id=contact.helcim_customer_id,
            discount=discount,
        )
    except Exception:
        # Release the claim so the invoice stays sendable after a failure.
        PreBillingInvoice.objects.filter(
            pk=invoice.pk, status='sending'
        ).update(status='draft')
        invoices_sent_total.labels(result='failed').inc()
        raise

    # Build payment URL from subdomain + token (per-school subdomain wins)
    payment_url = payment_page_url(helcim_response['token'], school)

    # Minimal atomic block ONLY for the DB write
    with transaction.atomic():
        invoice.helcim_invoice_id = str(helcim_response['invoiceId'])
        # Payment/webhook responses reference invoiceNumber, not invoiceId —
        # webhook reconciliation matches on this field.
        invoice.helcim_invoice_number = str(helcim_response.get('invoiceNumber', ''))
        invoice.payment_token = helcim_response['token']
        invoice.status = 'sent'
        invoice.save()
    invoices_sent_total.labels(result='sent').inc()

    # Email OUTSIDE atomic + after DB commit. Failure is recorded on the
    # invoice (email_sent/email_error) so management can resend or copy the
    # payment link from the UI — a failed email is recoverable, not silent.
    if projected:
        lesson_dates = [item['date'].strftime('%Y-%m-%d') for item in projected]
    else:
        lesson_dates = [
            l.scheduled_date.date().strftime('%Y-%m-%d')
            if l.scheduled_date is not None
            else 'Unknown'
            for l in lessons
        ]
    period_label = invoice.period_start.strftime('%B %Y')
    email_result, email_message = PreBillingEmailService.send_payment_request(
        contact.email,
        contact.student.get_full_name(),
        school.name,
        period_label,
        invoice.amount,
        lesson_dates,
        payment_url,
    )
    invoice.email_sent = email_result
    invoice.email_error = '' if email_result else email_message
    invoice.save(update_fields=['email_sent', 'email_error', 'updated_at'])
    if not email_result:
        logger.warning(
            'Pre-billing email failed for invoice %s: %s',
            invoice.id,
            email_message,
        )

