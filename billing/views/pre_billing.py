"""
billing/views/pre_billing.py

Pre-billing invoice endpoints for Phase 19.

Endpoints:
  POST /api/billing/management/pre-billing/generate/         → management_pre_billing_generate
  GET  /api/billing/management/pre-billing/                   → management_pre_billing_list
  GET  /api/billing/management/pre-billing/<invoice_id>/      → management_pre_billing_detail
  POST /api/billing/management/pre-billing/<invoice_id>/send/ → management_pre_billing_send
  POST /api/billing/management/pre-billing/send-all/          → management_pre_billing_send_all

Architectural constraint (STATE.md hard rule, T-19-03-06):
  All HelcimClient HTTP calls MUST be placed OUTSIDE any transaction.atomic() block.
  Violation orphans Helcim invoices when DB rolls back.
"""

import logging
import calendar
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from custom_auth.decorators import management_required
from ..models import (
    PreBillingInvoice,
    BillableContact,
    Lesson,
    StudentCreditAccount,
    RecurringLessonsSchedule,
)
from ..services.helcim_client import HelcimClient, HelcimAPIError, payment_page_url
from billing.metrics import invoices_sent_total
from ..services.email_service import PreBillingEmailService
from ..services.invoice_sending import (
    InvoiceSendConflict,
    projected_items as _projected_items,
    send_single_invoice as _send_single_invoice,
)

logger = logging.getLogger(__name__)
User = get_user_model()



# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _next_month(today):
    """Return (year, month) of the calendar month AFTER ``today`` (Dec → Jan rollover)."""
    if today.month == 12:
        return today.year + 1, 1
    return today.year, today.month + 1


def _period_for(year, month):
    """Return (period_start, period_end) for the first/last day of ``year``-``month``."""
    period_start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    period_end = date(year, month, last_day)
    return period_start, period_end


def _resolve_period(request):
    """
    Derive (period_start, period_end) from request-supplied ``month`` and ``year``.

    Source of params (B-2):
      - POST generate endpoint → request.data (JSON body)
      - GET list endpoint      → request.query_params

    Default (D-03/D-07): when both are absent, bill-ahead the NEXT calendar month
    relative to date.today() (handles December → January rollover).

    Validation (T-24-01): month must be 1–12 and year a 4-digit int. On any invalid
    or missing input the endpoint stays tolerant and falls back to next month rather
    than raising — no crash, no arbitrary period.
    """
    # GET requests carry params in the query string; everything else (POST) in the body.
    source = request.query_params if request.method == 'GET' else request.data

    raw_month = source.get('month')
    raw_year = source.get('year')

    today = date.today()
    default_year, default_month = _next_month(today)

    # Both absent → default to next month.
    if raw_month is None and raw_year is None:
        return _period_for(default_year, default_month)

    try:
        month = int(raw_month)
        year = int(raw_year)
    except (TypeError, ValueError):
        return _period_for(default_year, default_month)

    # Validate ranges: month 1–12, year a 4-digit value.
    if not (1 <= month <= 12) or not (1000 <= year <= 9999):
        return _period_for(default_year, default_month)

    return _period_for(year, month)



def _serialize_invoice(invoice):
    """Return a dict representation of a PreBillingInvoice for API responses."""
    lessons = list(invoice.lessons.select_related('teacher').order_by('scheduled_date'))
    contact = BillableContact.objects.filter(
        student=invoice.student, is_primary=True
    ).only('email').first()
    # Bill-ahead invoices (empty M2M) display projected schedule dates with
    # synthetic negative ids — they are not removable Lesson rows.
    projected = _projected_items(invoice) if not lessons else []
    return {
        'is_projected': bool(projected) or (not lessons and bool(invoice.excluded_dates)),
        'excluded_dates': sorted(invoice.excluded_dates or []),
        'id': invoice.id,
        'status': invoice.status,
        'amount': str(invoice.amount),
        'period_start': str(invoice.period_start),
        'period_end': str(invoice.period_end),
        'helcim_invoice_id': invoice.helcim_invoice_id,
        'helcim_invoice_number': invoice.helcim_invoice_number,
        'payment_token': invoice.payment_token,
        'payment_url': (
            payment_page_url(invoice.payment_token, invoice.school)
            if invoice.payment_token else ''
        ),
        'email_sent': invoice.email_sent,
        'email_error': invoice.email_error,
        'student': {
            'id': invoice.student_id,
            'full_name': invoice.student.get_full_name(),
            'email': invoice.student.email,
            'contact_email': contact.email if contact else invoice.student.email,
        },
        'lessons': [
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
        ],
    }



# ---------------------------------------------------------------------------
# View functions
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_pre_billing_generate(request):
    """
    POST /api/billing/management/pre-billing/generate/

    Incrementally generate draft PreBillingInvoice rows for all active students
    in request.user.school that have a primary BillableContact AND do not already
    have a PreBillingInvoice for the current period (any status).

    Idempotent and safe to call multiple times — supports wave-based batch
    approval where teachers submit at different times during the month.
    Students with an existing invoice (draft/sent/adjusted) are skipped so
    previously sent invoices are never duplicated.
    """
    school = request.user.school
    period_start, period_end = _resolve_period(request)

    # Sourcing precedence (D-08): FUTURE periods project from RecurringLessonsSchedule
    # (Lesson rows only exist after batch approval); CURRENT/PAST periods source from
    # actual confirmed Lesson rows (existing behavior preserved).
    today = date.today()
    is_future = (period_start.year, period_start.month) > (today.year, today.month)

    generated = 0
    skipped_existing = 0
    skipped_no_contact = 0
    skipped_no_schedule = 0  # D-09: students with zero projected/actual lessons

    # Map existing invoices for this period so drafts can be refreshed in place (D-10)
    # while sent/adjusted invoices are left untouched.
    existing_by_student = {
        inv.student_id: inv
        for inv in PreBillingInvoice.objects.filter(
            school=school,
            period_start=period_start,
        )
    }

    active_students = User.objects.filter(
        user_type='student',
        is_active=True,
        school=school,
    )

    for student in active_students:
        existing = existing_by_student.get(student.id)

        # D-10: sent/adjusted invoices are frozen — never touched on re-run.
        if existing is not None and existing.status in ('sent', 'adjusted'):
            skipped_existing += 1
            continue

        # Skip students without a primary billing contact
        try:
            BillableContact.objects.get(student=student, is_primary=True)
        except BillableContact.DoesNotExist:
            skipped_no_contact += 1
            continue

        if is_future:
            # FUTURE: project lessons from each active recurring schedule (D-04/D-08).
            # No Lesson rows are created; the M2M stays empty and amount is computed
            # from the projected dates. Mirrors get_scheduled_lessons_data pattern.
            schedules = RecurringLessonsSchedule.objects.filter(
                student=student,
                school=school,
                is_active=True,
            )
            projected_count = 0
            gross = Decimal('0.00')
            for sched in schedules:
                dates = sched.generate_lessons_for_month(
                    period_start.year, period_start.month
                )
                projected_count += len(dates)
                gross += (
                    Decimal(str(sched.student_rate))
                    * Decimal(str(sched.duration))
                    * len(dates)
                )
            has_lessons = projected_count > 0
            lessons = None  # no real Lesson rows for future periods
        else:
            # CURRENT/PAST: source from actual confirmed Lesson rows (unchanged).
            lessons = Lesson.objects.filter(
                student=student,
                school=school,
                status='confirmed',
                scheduled_date__date__range=(period_start, period_end),
            )
            # Gross amount: sum of student_rate × duration for each lesson
            # Formula matches Lesson.student_cost() pattern (models.py:334-341)
            gross = sum(
                (
                    Decimal(str(l.student_rate)) * Decimal(str(l.duration))
                    for l in lessons
                ),
                Decimal('0.00'),
            )
            has_lessons = lessons.exists()

        # D-09: no lessons projected/actual → do NOT create a $0 draft. Skip and count.
        if not has_lessons:
            skipped_no_schedule += 1
            continue

        # Read credit balance OUTSIDE atomic per Pitfall 6
        try:
            credit = StudentCreditAccount.objects.get(
                student=student,
                school=school,
            ).balance
        except StudentCreditAccount.DoesNotExist:
            credit = Decimal('0.00')

        amount = max(Decimal('0.00'), gross - credit)

        # Minimal atomic block for PreBillingInvoice creation/refresh + M2M set.
        # get_or_create on (student, school, period_start) is race-safe under the
        # unique_prebilling_per_student_period constraint.
        with transaction.atomic():
            invoice, created = PreBillingInvoice.objects.get_or_create(
                student=student,
                school=school,
                period_start=period_start,
                defaults={
                    'status': 'draft',
                    'amount': amount,
                    'period_end': period_end,
                },
            )
            if created:
                if lessons is not None:
                    invoice.lessons.set(lessons)
                generated += 1
            elif invoice.status == 'draft':
                # D-10: refresh existing DRAFT to current schedule amount + lessons.
                # Management-skipped dates survive the refresh: recompute from
                # the filtered projection instead of the raw schedule gross.
                if is_future and invoice.excluded_dates:
                    filtered_gross = sum(
                        (item['rate'] * item['duration']
                         for item in _projected_items(invoice)),
                        Decimal('0.00'),
                    )
                    amount = max(Decimal('0.00'), filtered_gross - credit)
                invoice.amount = amount
                invoice.period_end = period_end
                invoice.save(update_fields=['amount', 'period_end'])
                if lessons is not None:
                    invoice.lessons.set(lessons)
                else:
                    invoice.lessons.clear()
                generated += 1
            else:
                # Defensive: any non-draft slipped through (race) — leave untouched.
                skipped_existing += 1

    return Response(
        {
            'generated': generated,
            'skipped_existing': skipped_existing,
            'skipped_no_contact': skipped_no_contact,
            'skipped_no_schedule': skipped_no_schedule,
            'period_start': str(period_start),
            'period_end': str(period_end),
        }
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_pre_billing_list(request):
    """
    GET /api/billing/management/pre-billing/

    Return all PreBillingInvoice rows scoped to request.user.school.
    """
    qs = (
        PreBillingInvoice.objects
        .filter(school=request.user.school)
        .select_related('student')
        .prefetch_related('lessons')
        .order_by('-created_at')
    )
    return Response([_serialize_invoice(i) for i in qs])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_pre_billing_detail(request, invoice_id):
    """
    GET /api/billing/management/pre-billing/<invoice_id>/

    Return a single PreBillingInvoice scoped to request.user.school.
    Cross-school lookup returns 404 (T-19-03-02).
    """
    try:
        invoice = PreBillingInvoice.objects.get(
            id=invoice_id,
            school=request.user.school,
        )
    except PreBillingInvoice.DoesNotExist:
        return Response(
            {'error': 'Invoice not found'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(_serialize_invoice(invoice))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_pre_billing_send(request, invoice_id):
    """
    POST /api/billing/management/pre-billing/<invoice_id>/send/

    Lazy-create a Helcim customer (if missing), create a Helcim invoice
    with one lineItem per lesson date, persist helcim_invoice_id + payment_token,
    set status=sent, and send a Resend email.

    All Helcim HTTP calls are OUTSIDE transaction.atomic() (T-19-03-06).
    """
    try:
        invoice = PreBillingInvoice.objects.get(
            id=invoice_id,
            school=request.user.school,
        )
    except PreBillingInvoice.DoesNotExist:
        return Response(
            {'error': 'Invoice not found'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if invoice.status != 'draft':
        return Response(
            {'error': 'Only draft invoices can be sent'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        _send_single_invoice(invoice, request.user.school)
    except InvoiceSendConflict as e:
        return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
    except HelcimAPIError as e:
        logger.error('Helcim error sending invoice %s: %s', invoice_id, e)
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except BillableContact.DoesNotExist:
        return Response(
            {'error': 'No primary billing contact for this student'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            'id': invoice.id,
            'status': invoice.status,
            'helcim_invoice_id': invoice.helcim_invoice_id,
            'email_sent': invoice.email_sent,
            'email_error': invoice.email_error,
        }
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_pre_billing_remove_lesson(request, invoice_id):
    """
    POST /api/billing/management/pre-billing/<invoice_id>/remove-lesson/

    Remove a lesson from a sent/adjusted invoice via void+recreate:

    1. Validate invoice (school-scoped, status guard, lesson membership)
    2. OUTSIDE transaction: cancel old Helcim invoice (cancel_invoice)
       — on HelcimAPIError: return 400 inline, no DB change (BILL-09, D-16)
    3. Guard against last-lesson scenario AFTER successful cancel
    4. OUTSIDE transaction: create replacement Helcim invoice
    5. Minimal transaction.atomic for all DB writes
    6. OUTSIDE atomic: send replacement email

    All Helcim HTTP calls are OUTSIDE any transaction.atomic() block
    per the hard architectural constraint (STATE.md / T-19-04-06).
    """
    school = request.user.school

    # Step 1a: School-scoped invoice lookup
    try:
        invoice = (
            PreBillingInvoice.objects
            .select_related('student')
            .prefetch_related('lessons')
            .get(id=invoice_id, school=school)
        )
    except PreBillingInvoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

    # Step 1b: Status guard — only sent/adjusted invoices support removal
    if invoice.status not in ('sent', 'adjusted'):
        return Response(
            {'error': 'Only sent or adjusted invoices support lesson removal'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Step 1c: Validate lesson_id from request body
    lesson_id = request.data.get('lesson_id')
    if lesson_id is None:
        return Response({'error': 'lesson_id required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        lesson_id = int(lesson_id)
    except (ValueError, TypeError):
        return Response({'error': 'lesson_id must be integer'}, status=status.HTTP_400_BAD_REQUEST)

    # Step 1d: Look up lesson within the invoice's M2M set (T-19-04-02)
    try:
        lesson = invoice.lessons.get(id=lesson_id)
    except Lesson.DoesNotExist:
        return Response(
            {'error': 'Lesson not part of this invoice'},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Step 2: Compute remaining lessons (post-removal — used for line items + amount)
    remaining = list(invoice.lessons.exclude(id=lesson_id).order_by('scheduled_date'))

    # Step 3: Save old Helcim invoice ID before any state change
    old_helcim_invoice_id = invoice.helcim_invoice_id

    # Step 4: Build original line items from current invoice lessons (pre-removal)
    # Passed to cancel_invoice defensively per Pitfall 7 / A1 in 19-RESEARCH.md
    original_lessons = list(invoice.lessons.all().order_by('scheduled_date'))
    original_line_items = [
        {
            'description': (
                f"Lesson on {l.scheduled_date.date().strftime('%Y-%m-%d')}"
                if l.scheduled_date is not None
                else 'Lesson'
            ),
            'quantity': 1,
            'price': float(Decimal(str(l.student_rate)) * Decimal(str(l.duration))),
        }
        for l in original_lessons
    ]

    # Step 5: OUTSIDE transaction — cancel old Helcim invoice (T-19-04-06)
    # Cancel fires BEFORE the last-lesson guard so that a void failure on a
    # single-lesson invoice (test_void_failure_inline_error) surfaces the
    # "Cannot void" inline error rather than "Cannot remove last lesson" —
    # no DB change has occurred at this point (D-16).
    try:
        HelcimClient(school=school).cancel_invoice(
            old_helcim_invoice_id,
            currency='CAD',
            line_items=original_line_items,
        )
    except HelcimAPIError as e:
        logger.error(
            'cancel_invoice failed for invoice %s (helcim_id=%s): %s',
            invoice.id,
            old_helcim_invoice_id,
            e,
        )
        return Response(
            {'error': 'Cannot void — invoice may already be settled. Contact Helcim support.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Step 6: Last-lesson guard — check remaining count post-cancel
    # If this fires, the old Helcim invoice is already void but no DB write
    # has occurred; admin must manually handle the orphaned void in Helcim
    # (T-19-04-05 accepted risk — cancel+create both failed).
    if len(remaining) == 0:
        return Response(
            {'error': 'Cannot remove last lesson date. Cancel the invoice instead.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Step 7: Build replacement line items from remaining lessons (post-removal)
    line_items = [
        {
            # Helcim requires a sku for line items to appear on the invoice.
            'sku': f'LESSON-{l.pk}',
            'description': (
                f"Lesson on {l.scheduled_date.date().strftime('%Y-%m-%d')}"
                if l.scheduled_date is not None
                else 'Lesson'
            ),
            'quantity': 1,
            'price': float(Decimal(str(l.student_rate)) * Decimal(str(l.duration))),
        }
        for l in remaining
    ]

    # Step 8: Look up billing contact — customer must exist (set during original send)
    try:
        contact = BillableContact.objects.select_related('student').get(
            student=invoice.student,
            is_primary=True,
        )
    except BillableContact.DoesNotExist:
        return Response(
            {'error': 'No primary billing contact for this student'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not contact.helcim_customer_id:
        return Response(
            {'error': 'Contact missing Helcim customer ID — cannot recreate invoice'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Step 9: OUTSIDE transaction — create replacement Helcim invoice (T-19-04-06)
    try:
        helcim_response = HelcimClient(school=school).create_invoice(
            currency='CAD',
            line_items=line_items,
            customer_id=contact.helcim_customer_id,
        )
    except HelcimAPIError as e:
        # Inconsistent state: old invoice voided in Helcim, DB still reflects old ID.
        # Surface clearly so admin can manually recreate (T-19-04-05 accepted risk).
        logger.error(
            'create_invoice (replacement) failed for invoice %s after cancel: %s',
            invoice.id,
            e,
        )
        return Response(
            {'error': f'Replacement invoice creation failed: {e}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Step 10: Recompute amount from remaining lessons (D-11: no credit re-application at adjust)
    gross = sum(
        (Decimal(str(l.student_rate)) * Decimal(str(l.duration)) for l in remaining),
        Decimal('0.00'),
    )
    amount = max(Decimal('0.00'), gross)

    # Step 11: Build payment URL from subdomain + new token (per-school subdomain wins)
    payment_url = payment_page_url(helcim_response['token'], school)

    # Step 12: Minimal transaction.atomic for ALL DB writes (T-19-04-06)
    with transaction.atomic():
        invoice.lessons.remove(lesson)
        invoice.helcim_invoice_id = str(helcim_response['invoiceId'])
        invoice.helcim_invoice_number = str(helcim_response.get('invoiceNumber', ''))
        invoice.payment_token = helcim_response['token']
        invoice.status = 'adjusted'
        invoice.amount = amount
        invoice.save()

    # Step 13: OUTSIDE atomic — send replacement email (D-17)
    lesson_dates = [
        l.scheduled_date.date().strftime('%Y-%m-%d')
        if l.scheduled_date is not None
        else 'Unknown'
        for l in remaining
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
            'Replacement pre-billing email failed for invoice %s: %s',
            invoice.id,
            email_message,
        )

    return Response(_serialize_invoice(invoice))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_pre_billing_resend_email(request, invoice_id):
    """
    POST /api/billing/management/pre-billing/<invoice_id>/resend-email/

    Re-send the payment-request email for a sent/adjusted invoice using the
    existing Helcim payment token — no new Helcim invoice is created. This is
    the recovery path when the original email failed (email_sent=False) or a
    parent lost the link.
    """
    try:
        invoice = (
            PreBillingInvoice.objects
            .select_related('student', 'school')
            .prefetch_related('lessons')
            .get(id=invoice_id, school=request.user.school)
        )
    except PreBillingInvoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

    if invoice.status not in ('sent', 'adjusted'):
        return Response(
            {'error': 'Only sent or adjusted invoices can have their email resent'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not invoice.payment_token:
        return Response(
            {'error': 'Invoice has no payment link — send it first'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        contact = BillableContact.objects.select_related('student').get(
            student=invoice.student,
            is_primary=True,
        )
    except BillableContact.DoesNotExist:
        return Response(
            {'error': 'No primary billing contact for this student'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    payment_url = payment_page_url(invoice.payment_token, invoice.school)
    resend_lessons = list(invoice.lessons.all().order_by('scheduled_date'))
    if resend_lessons:
        lesson_dates = [
            l.scheduled_date.date().strftime('%Y-%m-%d')
            if l.scheduled_date is not None
            else 'Unknown'
            for l in resend_lessons
        ]
    else:
        # Bill-ahead invoice — dates come from the schedule projection
        lesson_dates = [
            item['date'].strftime('%Y-%m-%d') for item in _projected_items(invoice)
        ]
    email_result, email_message = PreBillingEmailService.send_payment_request(
        contact.email,
        contact.student.get_full_name(),
        invoice.school.name,
        invoice.period_start.strftime('%B %Y'),
        invoice.amount,
        lesson_dates,
        payment_url,
    )
    invoice.email_sent = email_result
    invoice.email_error = '' if email_result else email_message
    invoice.save(update_fields=['email_sent', 'email_error', 'updated_at'])

    if not email_result:
        return Response(
            {'error': email_message, **_serialize_invoice(invoice)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response(_serialize_invoice(invoice))


def _toggle_projected_date(request, invoice_id, skip):
    """
    Shared body for skip-date / restore-date.

    Draft, schedule-projected invoices only — one-off date exclusions for a
    known absence. The schedule itself is untouched; recurring changes belong
    on the schedule (or a pause), not here. Amount is recomputed from the
    filtered projection minus current credit, mirroring generate.
    """
    try:
        invoice = PreBillingInvoice.objects.get(
            id=invoice_id,
            school=request.user.school,
        )
    except PreBillingInvoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

    if invoice.status != 'draft':
        return Response(
            {'error': 'Dates can only be skipped on draft invoices'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if invoice.lessons.exists():
        return Response(
            {'error': 'This invoice bills actual lessons — use Remove Lesson instead'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    raw_date = str(request.data.get('date', ''))
    try:
        target = date.fromisoformat(raw_date)
    except ValueError:
        return Response(
            {'error': 'date must be YYYY-MM-DD'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    excluded = set(invoice.excluded_dates or [])
    if skip:
        # Must be a real projected date (and not already skipped)
        projectable = {item['date'].isoformat() for item in _projected_items(invoice)}
        if target.isoformat() not in projectable:
            return Response(
                {'error': 'Date is not on this invoice'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        excluded.add(target.isoformat())
    else:
        if target.isoformat() not in excluded:
            return Response(
                {'error': 'Date is not skipped'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        excluded.discard(target.isoformat())

    invoice.excluded_dates = sorted(excluded)

    # Recompute amount from the filtered projection − current credit
    remaining = sum(
        (item['rate'] * item['duration'] for item in _projected_items(invoice)),
        Decimal('0.00'),
    ).quantize(Decimal('0.01'))
    try:
        credit = StudentCreditAccount.objects.get(
            student=invoice.student, school=invoice.school
        ).balance
    except StudentCreditAccount.DoesNotExist:
        credit = Decimal('0.00')
    invoice.amount = max(Decimal('0.00'), remaining - credit)

    with transaction.atomic():
        invoice.save(update_fields=['excluded_dates', 'amount', 'updated_at'])

    return Response(_serialize_invoice(invoice))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_pre_billing_skip_date(request, invoice_id):
    """POST /api/billing/management/pre-billing/<invoice_id>/skip-date/  {date: YYYY-MM-DD}"""
    return _toggle_projected_date(request, invoice_id, skip=True)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_pre_billing_restore_date(request, invoice_id):
    """POST /api/billing/management/pre-billing/<invoice_id>/restore-date/  {date: YYYY-MM-DD}"""
    return _toggle_projected_date(request, invoice_id, skip=False)
