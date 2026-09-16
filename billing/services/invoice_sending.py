"""
Single-invoice send pipeline for pre-billing (Helcim invoice + payment email).

Extracted verbatim from views/pre_billing.py (batch-queue wave phase 1) so the
send-run worker and the HTTP views share one implementation. Behavior contract
unchanged:
- All HelcimClient HTTP calls stay OUTSIDE any transaction.atomic() block
  (STATE.md / T-19-03-06) — wrapping them orphans Helcim invoices on rollback.
- The conditional UPDATE claim is the double-send lock (MAP-185): it accepts
  a draft, or an unresolved send (sending/unknown) whose attempt id the caller
  read. Exactly one caller wins. A failed send does NOT release the claim —
  the row stays sending/unknown and the next attempt looks the previous
  attempt's Helcim number up before creating again, so one successful send
  means exactly one Helcim invoice.
"""
import logging
import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from ..models import (
    BillableContact,
    PreBillingInvoice,
    RecurringLessonsSchedule,
    StudentCreditAccount,
)
from .helcim_client import (
    HelcimClient,
    HelcimAPIError,
    HelcimInvoiceNumberExists,
    payment_page_url,
)
from .email_service import PreBillingEmailService
from billing.metrics import invoices_sent_total

logger = logging.getLogger(__name__)


class InvoiceSendConflict(Exception):
    """Raised when an invoice is not in a sendable state (double-send guard)."""


def helcim_invoice_number(invoice_pk, attempt_id):
    """
    Client-supplied Helcim invoiceNumber for one send attempt (MAP-185):
    MK{pk}-{uuid hex[:8]}. The uuid slice keeps numbers unique across the
    shared test account every local dev DB talks to; the number is visible
    to parents (accepted).
    """
    return f"MK{invoice_pk}-{attempt_id.hex[:8]}"



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


def issued_line_items(lessons, projected):
    """
    Serialized line items for an invoice, in the API's `lessons` shape.

    Lesson rows keep their real ids; projected items carry synthetic negative
    ids (they are not removable rows). This is the shape written to
    PreBillingInvoice.issued_items at send time (MAP-186) and returned by the
    serializer, so a sent/adjusted/paid invoice displays exactly what was
    issued and is never re-projected from current schedules.
    """
    return [
        {
            'id': l.id,
            'scheduled_date': (
                l.scheduled_date.date().isoformat()
                if l.scheduled_date is not None
                else None
            ),
            'duration': str(l.duration),
            'student_rate': str(l.student_rate),
            'charge': str(
                (Decimal(str(l.student_rate)) * Decimal(str(l.duration)))
                .quantize(Decimal('0.01'))
            ),
            'teacher_name': l.teacher.get_full_name() if l.teacher else '',
        }
        for l in lessons
    ] + [
        {
            'id': -(i + 1),
            'scheduled_date': item['date'].isoformat(),
            'duration': str(item['duration']),
            'student_rate': str(item['rate']),
            'charge': str((item['rate'] * item['duration']).quantize(Decimal('0.01'))),
            'teacher_name': item['teacher_name'],
        }
        for i, item in enumerate(projected)
    ]



def credit_discount(line_items, amount):
    """
    Wallet credit as a Helcim invoice-level discount, or None.

    `amount` is net of wallet credit but the line items are gross — without a
    discount Helcim would charge the parent MORE than the emailed amount.
    Credit rides as an invoice-level discount (negative line-item prices are
    rejected by the API), keeping Helcim's amountDue == amount == emailed
    amount. Shared by the send pipeline and the remove-lesson adjustment
    (MAP-184), so both paths apply credit the same way.
    """
    gross = sum(
        (Decimal(str(li['price'])) for li in line_items),
        Decimal('0.00'),
    ).quantize(Decimal('0.01'))
    credit_applied = gross - amount
    if credit_applied > Decimal('0.00'):
        return {
            'amount': float(credit_applied),
            'details': 'Account credit applied',
        }
    return None


def send_single_invoice(invoice, school):
    """
    Send a PreBillingInvoice via Helcim and email — a draft, or an unresolved
    earlier attempt (status='sending', send_outcome='unknown').

    All HelcimClient HTTP calls are OUTSIDE any transaction.atomic() block
    per the hard architectural constraint (STATE.md / T-19-03-06).

    MAP-185 contract:
    - The claim records a fresh attempt id; the Helcim number for the attempt
      is derived from it. A failure of unknown outcome never returns the row
      to draft.
    - Every retry first looks the previous attempt's number up at Helcim and
      adopts it if present; only if absent does it create, under the new
      number. A 400 "Invoice Number already existed" on create is "found".

    Args:
        invoice: PreBillingInvoice instance
        school: School instance (for URL assembly + email sign-off)

    Raises:
        InvoiceSendConflict: another caller holds the claim
        BillableContact.DoesNotExist: if no primary contact found
        HelcimAPIError: if Helcim create_customer / lookup / create_invoice fails
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
    # Helcim page all agree at the moment of sending. The claim below writes
    # it, so every later attempt of this send uses the amount the Helcim
    # invoice was created with (MAP-185).
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

    # Claim (MAP-185): one conditional UPDATE accepts a draft, or an
    # unresolved send whose attempt id is the one this caller read. Rotating
    # the id in the same statement is what makes a second concurrent re-send
    # lose. Exactly one caller wins; the loser gets a conflict.
    previous_attempt_id = invoice.send_attempt_id
    previous_number = (
        helcim_invoice_number(invoice.pk, previous_attempt_id)
        if previous_attempt_id is not None
        else None
    )
    new_attempt_id = uuid.uuid4()
    claimable = Q(status='draft')
    if previous_attempt_id is not None:
        claimable |= Q(
            status='sending',
            send_outcome='unknown',
            send_attempt_id=previous_attempt_id,
        )
    claimed = PreBillingInvoice.objects.filter(
        Q(pk=invoice.pk) & claimable
    ).update(
        status='sending',
        send_outcome='unknown',
        send_attempt_id=new_attempt_id,
        amount=invoice.amount,
    )
    if not claimed:
        raise InvoiceSendConflict(
            'This invoice is already being sent or was already sent.'
        )
    # Mirror the claim on the instance so the final save() cannot write
    # stale values back over it.
    invoice.status = 'sending'
    invoice.send_outcome = 'unknown'
    invoice.send_attempt_id = new_attempt_id
    number = helcim_invoice_number(invoice.pk, new_attempt_id)

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

        client = HelcimClient(school=school)
        helcim_response = None

        # Lookup-first (MAP-185): a previous attempt may have created the
        # invoice without our hearing back. Adopt it rather than create twice.
        # A first send from draft has no previous attempt and goes straight
        # to create.
        if previous_number is not None:
            helcim_response = client.get_invoice_by_number(previous_number)
            if helcim_response is not None:
                number = previous_number

        if helcim_response is None:
            # Create Helcim invoice — OUTSIDE transaction
            try:
                helcim_response = client.create_invoice(
                    currency='CAD',
                    line_items=line_items,
                    customer_id=contact.helcim_customer_id,
                    discount=credit_discount(line_items, invoice.amount),
                    invoice_number=number,
                )
            except HelcimInvoiceNumberExists:
                # Helcim already holds this number: the create we never heard
                # back from went through. Treat as found — look it up, adopt.
                helcim_response = client.get_invoice_by_number(number)
                if helcim_response is None:
                    raise
    except Exception:
        # The claim is NOT released (MAP-185): the row stays sending/unknown
        # and the next attempt looks the number up before creating again.
        invoices_sent_total.labels(result='failed').inc()
        raise

    # Build payment URL from subdomain + token (per-school subdomain wins)
    payment_url = payment_page_url(helcim_response['token'], school)

    # Minimal atomic block ONLY for the DB write
    with transaction.atomic():
        invoice.helcim_invoice_id = str(helcim_response['invoiceId'])
        # Our number for this attempt (MK{pk}-{attempt}; Helcim echoes it).
        # Payment/webhook responses reference invoiceNumber, not invoiceId —
        # webhook reconciliation matches on this field.
        invoice.helcim_invoice_number = number
        invoice.payment_token = helcim_response['token']
        invoice.status = 'sent'
        invoice.send_outcome = 'sent'
        # Snapshot the issued line items (MAP-186): from here on the invoice
        # displays these, never a re-projection of the current schedules.
        invoice.issued_items = issued_line_items(lessons, projected)
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

