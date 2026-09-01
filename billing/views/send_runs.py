"""
Invoice send-run endpoints (batch-queue wave).

"Send all" no longer performs Helcim/email work in the request: it snapshots
the period's draft invoices into an InvoiceSendRun (cutoff semantics — drafts
created afterwards are not in the run) and returns 202 immediately. The
send-run worker (process_invoice_send_runs) drains the items; the frontend
polls the run detail endpoint for progress.
"""
import logging
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from custom_auth.decorators import management_required
from ..models import InvoiceSendItem, InvoiceSendRun, PreBillingInvoice

logger = logging.getLogger(__name__)

LIVE_RUN_STATUSES = ('queued', 'running')


def _serialize_run(run):
    """Run detail for the polling UI: counts on the row, failures per item."""
    failures = [
        {
            'invoice_id': item.invoice_id,
            'student_id': item.invoice.student_id,
            'student_name': item.invoice.student.get_full_name(),
            'error': item.last_error,
        }
        for item in run.items.filter(status='failed').select_related('invoice__student')
    ]
    return {
        'id': run.id,
        'status': run.status,
        'month': run.period_start.month,
        'year': run.period_start.year,
        'item_count': run.item_count,
        'sent_count': run.sent_count,
        'failed_count': run.failed_count,
        'failures': failures,
        'created_at': run.created_at,
        'finished_at': run.finished_at,
    }


def _parse_period_start(data):
    """Return a period_start date from required month/year body params, or None."""
    try:
        return date(int(data.get('year')), int(data.get('month')), 1)
    except (TypeError, ValueError):
        return None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_pre_billing_send_all(request):
    """
    POST /api/billing/management/pre-billing/send-all/  body: {month, year}

    Snapshot the period's draft invoices into a send run and return 202 with
    the run — no Helcim or email calls happen here. 409 when a run for the
    period is already live (response carries its id so the UI can attach).
    """
    period_start = _parse_period_start(request.data)
    if period_start is None:
        return Response(
            {'error': 'month and year are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    school = request.user.school
    live = InvoiceSendRun.objects.filter(
        school=school, period_start=period_start, status__in=LIVE_RUN_STATUSES
    ).first()
    if live:
        return Response(
            {'error': 'A send run for this period is already in progress.',
             'run_id': live.id},
            status=status.HTTP_409_CONFLICT,
        )

    draft_ids = list(
        PreBillingInvoice.objects
        .filter(school=school, status='draft', period_start=period_start)
        .order_by('id')
        .values_list('id', flat=True)
    )
    if not draft_ids:
        return Response(
            {'error': 'No draft invoices to send for this period.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        with transaction.atomic():
            run = InvoiceSendRun.objects.create(
                school=school,
                period_start=period_start,
                created_by=request.user,
                item_count=len(draft_ids),
            )
            InvoiceSendItem.objects.bulk_create([
                InvoiceSendItem(run=run, invoice_id=invoice_id, position=pos)
                for pos, invoice_id in enumerate(draft_ids)
            ])
    except IntegrityError:
        # Lost a race with a concurrent send-all (run- or item-level unique
        # constraint) — report the live run instead of failing opaquely.
        live = InvoiceSendRun.objects.filter(
            school=school, period_start=period_start, status__in=LIVE_RUN_STATUSES
        ).first()
        return Response(
            {'error': 'A send run for this period is already in progress.',
             'run_id': live.id if live else None},
            status=status.HTTP_409_CONFLICT,
        )

    logger.info(
        'Send run %s queued: school=%s period=%s items=%s by user=%s',
        run.id, school.id, period_start, len(draft_ids), request.user.id,
    )
    return Response(_serialize_run(run), status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_send_run_detail(request, run_id):
    """GET /api/billing/management/send-runs/<id>/ — progress for the polling UI."""
    try:
        run = InvoiceSendRun.objects.get(pk=run_id, school=request.user.school)
    except InvoiceSendRun.DoesNotExist:
        return Response({'error': 'Send run not found'},
                        status=status.HTTP_404_NOT_FOUND)
    return Response(_serialize_run(run))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@management_required
def management_send_run_latest(request):
    """
    GET /api/billing/management/send-runs/latest/?month=&year=

    Latest run for the period (any status) or {run: null}. Lets the page
    re-attach to a live run after a refresh instead of double-queuing.
    """
    period_start = _parse_period_start(request.query_params)
    if period_start is None:
        return Response(
            {'error': 'month and year are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    run = (
        InvoiceSendRun.objects
        .filter(school=request.user.school, period_start=period_start)
        .order_by('-created_at')
        .first()
    )
    return Response({'run': _serialize_run(run) if run else None})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@management_required
def management_send_run_cancel(request, run_id):
    """
    POST /api/billing/management/send-runs/<id>/cancel/

    Flip the run's remaining pending items to skipped and the run to
    cancelled. An item the worker already claimed ('sending') finishes on its
    own — cancel stops future work, it does not interrupt an in-flight send.
    """
    try:
        run = InvoiceSendRun.objects.get(pk=run_id, school=request.user.school)
    except InvoiceSendRun.DoesNotExist:
        return Response({'error': 'Send run not found'},
                        status=status.HTTP_404_NOT_FOUND)
    if run.status not in LIVE_RUN_STATUSES:
        return Response(
            {'error': f'Run is already {run.status} and cannot be cancelled.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        skipped = run.items.filter(status='pending').update(
            status='skipped', finished_at=timezone.now()
        )
        InvoiceSendRun.objects.filter(pk=run.pk).update(
            status='cancelled', finished_at=timezone.now()
        )
    logger.info('Send run %s cancelled by user=%s (%s items skipped)',
                run.id, request.user.id, skipped)
    run.refresh_from_db()
    return Response(_serialize_run(run))
