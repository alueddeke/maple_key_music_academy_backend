"""
Unit tests for billing.services.helcim_csv_generator.generate_helcim_csv().

Protects Helcim CSV correctness: per-lesson row emission, zero-charge filter,
billing contact propagation, and degenerate edge cases.

Design follows D-06 testing principles (Phase 16 CONTEXT.md):
  1. Fail safely, fail fast, fail closed — no open states, no default values, everything explicit.
  2. 100% backend test coverage — every code path exercised.
  3. Every path needs 1 happy path + 1 failing path — contrast ensures accuracy.
  4. Test behaviour, not implementation — what the code does, not how it does it.
  5. Ideal and non-ideal circumstances covered.
  6. No implicit defaults — all assertions explicit; never pass silently with missing data.
"""

import csv
import pytest
from decimal import Decimal
from datetime import date, time
from io import StringIO

from billing.models import MonthlyInvoiceBatch, BatchLessonItem, StudentInvoice
from billing.services.helcim_csv_generator import generate_helcim_csv


# ---------------------------------------------------------------------------
# CSV parsing helper
# ---------------------------------------------------------------------------

def parse_csv_rows(response):
    """Parse HttpResponse CSV content into a list of row dicts (header excluded)."""
    content = response.content.decode('utf-8')
    reader = csv.DictReader(StringIO(content))
    return list(reader)


# ---------------------------------------------------------------------------
# Factory helpers — explicit sentinel values per D-06 (no implicit defaults)
# ---------------------------------------------------------------------------

def _make_batch(teacher, school, batch_number='BATCH-2026-01-T1', month=1, year=2026):
    return MonthlyInvoiceBatch.objects.create(
        batch_number=batch_number,
        teacher=teacher,
        school=school,
        month=month,
        year=year,
    )


def _make_lesson_item(
    batch,
    student,
    scheduled_date,
    status='completed',
    duration=Decimal('1.0'),
    student_rate=Decimal('60.00'),
    teacher_rate=Decimal('45.00'),
    start_time=time(10, 0),
    lesson_type='online',
):
    return BatchLessonItem.objects.create(
        batch=batch,
        student=student,
        scheduled_date=scheduled_date,
        start_time=start_time,
        duration=duration,
        lesson_type=lesson_type,
        teacher_rate=teacher_rate,
        student_rate=student_rate,
        status=status,
    )


def _make_invoice(batch, student, school, invoice_number='INV-2026-01-S1-0001'):
    return StudentInvoice.objects.create(
        batch=batch,
        student=student,
        school=school,
        invoice_number=invoice_number,
        amount=Decimal('0.00'),
        billing_contact_name='Test Parent',
        billing_email='parent@test.com',
        billing_phone='416-555-0001',
        billing_street_address='123 Test St',
        billing_city='Toronto',
        billing_province='ON',
        billing_postal_code='M5H 2N2',
    )


# ---------------------------------------------------------------------------
# Class 1 — Row emission happy paths
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRowEmission:
    """Happy paths: completed lessons produce the correct number of CSV data rows."""

    def test_completed_lesson_emits_one_row(self, school, school_settings, teacher_user, student_user):
        """One completed BatchLessonItem → exactly 1 CSV data row (excluding header)."""
        batch = _make_batch(teacher_user, school)
        invoice = _make_invoice(batch, student_user, school)
        item = _make_lesson_item(
            batch, student_user, scheduled_date=date(2026, 1, 15), status='completed'
        )
        invoice.lesson_items.set([item])

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 1

    def test_multiple_lessons_emit_multiple_rows(self, school, school_settings, teacher_user, student_user):
        """Four completed BatchLessonItems on one invoice → exactly 4 CSV data rows (CSV-01 acceptance scenario)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T2')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0002')

        scheduled_dates = [
            date(2026, 1, 15),
            date(2026, 1, 22),
            date(2026, 1, 29),
            date(2026, 2, 5),
        ]
        items = [
            _make_lesson_item(batch, student_user, scheduled_date=d, status='completed')
            for d in scheduled_dates
        ]
        invoice.lesson_items.set(items)

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 4


# ---------------------------------------------------------------------------
# Class 2 — Zero-charge filter (trial and cancelled lessons skipped)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestZeroChargeFilter:
    """Zero-charge lessons (trial, cancelled) are excluded from CSV output."""

    def test_trial_lesson_is_skipped(self, school, school_settings, teacher_user, student_user):
        """A BatchLessonItem with explicit status='trial' produces 0 data rows."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T3')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0003')
        # Explicit status='trial' preserved because student_user has a prior Lesson (auto-trial guard won't fire)
        item = _make_lesson_item(
            batch, student_user, scheduled_date=date(2026, 1, 15), status='trial'
        )
        invoice.lesson_items.set([item])

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 0

    def test_cancelled_lesson_is_skipped(self, school, school_settings, teacher_user, student_user):
        """A BatchLessonItem with status='cancelled' produces 0 data rows."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T4')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0004')
        item = _make_lesson_item(
            batch, student_user, scheduled_date=date(2026, 1, 15), status='cancelled'
        )
        invoice.lesson_items.set([item])

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 0

    def test_all_zero_charge_lessons_returns_zero_data_rows(self, school, school_settings, teacher_user, student_user):
        """Invoice with only trial + cancelled lessons → 0 data rows (degenerate non-ideal path)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T5')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0005')
        trial_item = _make_lesson_item(
            batch, student_user, scheduled_date=date(2026, 1, 15), status='trial'
        )
        cancelled_item = _make_lesson_item(
            batch, student_user, scheduled_date=date(2026, 1, 22), status='cancelled'
        )
        invoice.lesson_items.set([trial_item, cancelled_item])

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 0

    def test_mixed_lessons_emits_only_nonzero_rows(self, school, school_settings, teacher_user, student_user):
        """2 completed + 1 trial + 1 cancelled → exactly 2 rows (filter neither over-skips nor under-skips)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T6')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0006')
        items = [
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 5), status='completed'),
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 12), status='completed'),
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 19), status='trial'),
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 26), status='cancelled'),
        ]
        invoice.lesson_items.set(items)

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 2


# ---------------------------------------------------------------------------
# Class 3 — Row field values (AMOUNT, ORDER_NUMBER, COMMENTS, billing contact)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRowFieldValues:
    """Per-row column values match D-01/D-02/D-03 decisions and billing contact propagation."""

    def test_row_amount_equals_student_charge(self, school, school_settings, teacher_user, student_user):
        """AMOUNT column = student_rate × duration formatted to 2 decimal places (D-02)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T7')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0007')
        # 60.00 × 1.5 = 90.00
        item = _make_lesson_item(
            batch, student_user,
            scheduled_date=date(2026, 1, 15),
            status='completed',
            student_rate=Decimal('60.00'),
            duration=Decimal('1.5'),
        )
        invoice.lesson_items.set([item])

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert rows[0]['AMOUNT'] == '90.00'

    def test_row_order_number_is_invoice_number_shared(self, school, school_settings, teacher_user, student_user):
        """All lesson rows for one invoice share the same ORDER_NUMBER (D-01)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T8')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0008')
        items = [
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 5), status='completed'),
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 12), status='completed'),
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 19), status='completed'),
        ]
        invoice.lesson_items.set(items)

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 3
        for row in rows:
            assert row['ORDER_NUMBER'] == 'INV-2026-01-S1-0008'

    def test_row_comments_contains_formatted_date(self, school, school_settings, teacher_user, student_user):
        """COMMENTS column matches '%b %-d, %Y' format (D-03): abbreviated month, no leading zero, 4-digit year."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T9')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0009')
        # Jan 5 → 'Jan 5, 2026' (no leading zero); Dec 15 → 'Dec 15, 2026' (double-digit month)
        item_jan = _make_lesson_item(
            batch, student_user, scheduled_date=date(2026, 1, 5), status='completed'
        )
        item_dec = _make_lesson_item(
            batch, student_user, scheduled_date=date(2026, 12, 15), status='completed'
        )
        invoice.lesson_items.set([item_jan, item_dec])

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 2
        comments = {row['COMMENTS'] for row in rows}
        assert 'Jan 5, 2026' in comments
        assert 'Dec 15, 2026' in comments

    def test_billing_contact_fields_copied_to_each_row(self, school, school_settings, teacher_user, student_user):
        """Every lesson row carries the StudentInvoice billing_* fields verbatim."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T10')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0010')
        items = [
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 5), status='completed'),
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 12), status='completed'),
            _make_lesson_item(batch, student_user, scheduled_date=date(2026, 1, 19), status='completed'),
        ]
        invoice.lesson_items.set(items)

        response = generate_helcim_csv([invoice], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 3
        for row in rows:
            assert row['BILLING_CONTACT_NAME'] == 'Test Parent'
            assert row['BILLING_EMAIL'] == 'parent@test.com'
            assert row['BILLING_STREET1'] == '123 Test St'
            assert row['BILLING_CITY'] == 'Toronto'
            assert row['BILLING_PROVINCE'] == 'ON'
            assert row['BILLING_POSTALCODE'] == 'M5H 2N2'
            assert row['BILLING_PHONE'] == '416-555-0001'
            assert row['BILLING_COUNTRY'] == 'Canada'


# ---------------------------------------------------------------------------
# Class 4 — Degenerate cases
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDegenerateCases:
    """Edge cases: empty input and filename construction."""

    def test_empty_invoice_list_returns_zero_data_rows(self, school_settings):
        """Empty invoice list → 0 data rows; response is still valid CSV with header only."""
        response = generate_helcim_csv([], school_settings)
        rows = parse_csv_rows(response)

        assert len(rows) == 0
        assert response['Content-Type'] == 'text/csv'

    def test_response_filename_uses_batch_number_when_invoices_present(
        self, school, school_settings, teacher_user, student_user
    ):
        """Content-Disposition filename contains batch_number (not a generic timestamp)."""
        batch = _make_batch(teacher_user, school, batch_number='BATCH-2026-01-T11')
        invoice = _make_invoice(batch, student_user, school, invoice_number='INV-2026-01-S1-0011')
        item = _make_lesson_item(
            batch, student_user, scheduled_date=date(2026, 1, 15), status='completed'
        )
        invoice.lesson_items.set([item])

        response = generate_helcim_csv([invoice], school_settings)

        assert 'BATCH-2026-01-T11' in response['Content-Disposition']
        assert response['Content-Disposition'].startswith('attachment; filename=')
