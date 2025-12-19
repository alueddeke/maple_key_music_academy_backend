"""
Unit tests for invoice and lesson cost calculations with dual-rate system.

CRITICAL: These tests protect money calculations - invoice totals must be exact.

Dual-Rate System:
- teacher_rate: Amount paid to teacher for lesson
- student_rate: Amount billed to student for lesson
- Invoice.calculate_payment_balance() uses teacher_rate for teacher_payment, student_rate for student_billing
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from billing.models import Lesson, Invoice, User


@pytest.mark.django_db
class TestLessonCostCalculation:
    """Test lesson cost = rate × duration calculations."""

    def test_lesson_total_cost_whole_hours(self, teacher_user, student_user):
        """Test cost calculation for whole hour lessons."""
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("50.00"),
            student_rate=Decimal("100.00"),
            duration=Decimal("1.0"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="in_person"
        )

        # total_cost() still uses 'rate' which syncs with teacher_rate
        assert lesson.total_cost() == Decimal("50.00")

    def test_lesson_total_cost_partial_hours(self, teacher_user, student_user):
        """Test cost calculation for partial hour lessons (e.g., 1.5 hours)."""
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("80.00"),
            student_rate=Decimal("100.00"),
            duration=Decimal("1.5"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="in_person"
        )

        # CRITICAL: 1.5 hours at $80/hr should be $120, not $80
        assert lesson.total_cost() == Decimal("120.00")

    def test_lesson_total_cost_quarter_hours(self, teacher_user, student_user):
        """Test cost calculation for 15-minute increments."""
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("80.00"),
            student_rate=Decimal("100.00"),
            duration=Decimal("0.25"),  # 15 minutes
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="in_person"
        )

        assert lesson.total_cost() == Decimal("20.00")

    def test_lesson_total_cost_different_rates(self, teacher_user, student_user):
        """Test cost calculation with different hourly rates."""
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("100.00"),  # Higher rate
            student_rate=Decimal("120.00"),
            duration=Decimal("2.0"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="in_person"
        )

        assert lesson.total_cost() == Decimal("200.00")

    def test_lesson_total_cost_uses_decimal_precision(self, teacher_user, student_user):
        """Test that cost calculation maintains Decimal precision (no floating point errors)."""
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("45.00"),  # Online lesson rate
            student_rate=Decimal("60.00"),
            duration=Decimal("1.5"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="online"
        )

        # Should be exactly 67.50, not 67.49999999
        assert lesson.total_cost() == Decimal("67.50")
        assert isinstance(lesson.total_cost(), Decimal)


@pytest.mark.django_db
class TestInvoicePaymentBalance:
    """Test invoice payment_balance = sum of lesson costs using correct rate by type."""

    def test_teacher_invoice_uses_teacher_rate(self, teacher_user, student_user):
        """Test that teacher payment invoices use teacher_rate."""
        invoice = Invoice.objects.create(
            invoice_type="teacher_payment",
            teacher=teacher_user,
            payment_balance=Decimal("0.00"),
            due_date=datetime.now() + timedelta(days=30),
            status="pending"
        )

        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("50.00"),  # Teacher gets $50
            student_rate=Decimal("100.00"),  # Student pays $100
            duration=Decimal("1.0"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="in_person"
        )

        invoice.lessons.add(lesson)

        # Teacher invoice should use teacher_rate ($50)
        total = invoice.calculate_payment_balance()
        assert total == Decimal("50.00")

    def test_student_invoice_uses_student_rate(self, teacher_user, student_user):
        """Test that student billing invoices use student_rate."""
        invoice = Invoice.objects.create(
            invoice_type="student_billing",
            student=student_user,
            payment_balance=Decimal("0.00"),
            due_date=datetime.now() + timedelta(days=30),
            status="pending"
        )

        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("50.00"),  # Teacher gets $50
            student_rate=Decimal("100.00"),  # Student pays $100
            duration=Decimal("1.0"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="in_person"
        )

        invoice.lessons.add(lesson)

        # Student invoice should use student_rate ($100)
        total = invoice.calculate_payment_balance()
        assert total == Decimal("100.00")

    def test_invoice_payment_balance_multiple_lessons(self, teacher_user, student_user):
        """Test invoice total with multiple lessons of varying durations."""
        invoice = Invoice.objects.create(
            invoice_type="teacher_payment",
            teacher=teacher_user,
            payment_balance=Decimal("0.00"),
            due_date=datetime.now() + timedelta(days=30),
            status="pending"
        )

        # Create 3 lessons with different durations
        lessons = [
            Lesson.objects.create(
                teacher=teacher_user,
                student=student_user,
                teacher_rate=Decimal("80.00"),
                student_rate=Decimal("100.00"),
                duration=Decimal("1.0"),
                scheduled_date=datetime.now(),
                status="completed",
                lesson_type="in_person"
            ),
            Lesson.objects.create(
                teacher=teacher_user,
                student=student_user,
                teacher_rate=Decimal("80.00"),
                student_rate=Decimal("100.00"),
                duration=Decimal("1.5"),
                scheduled_date=datetime.now(),
                status="completed",
                lesson_type="in_person"
            ),
            Lesson.objects.create(
                teacher=teacher_user,
                student=student_user,
                teacher_rate=Decimal("80.00"),
                student_rate=Decimal("100.00"),
                duration=Decimal("0.5"),
                scheduled_date=datetime.now(),
                status="completed",
                lesson_type="in_person"
            ),
        ]

        for lesson in lessons:
            invoice.lessons.add(lesson)

        # Total should be: 80 + 120 + 40 = 240 (using teacher_rate)
        total = invoice.calculate_payment_balance()
        assert total == Decimal("240.00")

    def test_invoice_payment_balance_mixed_lesson_types(self, teacher_user, student_user):
        """Test invoice total with both online and in-person lessons (different rates)."""
        invoice = Invoice.objects.create(
            invoice_type="teacher_payment",
            teacher=teacher_user,
            payment_balance=Decimal("0.00"),
            due_date=datetime.now() + timedelta(days=30),
            status="pending"
        )

        # In-person lesson: teacher gets $80/hr, student pays $100/hr
        lesson1 = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("80.00"),
            student_rate=Decimal("100.00"),
            duration=Decimal("1.0"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="in_person"
        )

        # Online lesson: teacher gets $45/hr, student pays $60/hr
        lesson2 = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("45.00"),
            student_rate=Decimal("60.00"),
            duration=Decimal("1.0"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="online"
        )

        invoice.lessons.add(lesson1, lesson2)

        # Total should be: 80 + 45 = 125 (using teacher_rate for teacher payment)
        total = invoice.calculate_payment_balance()
        assert total == Decimal("125.00")

    def test_student_invoice_dual_rate_difference(self, teacher_user, student_user):
        """Test that student pays more than teacher receives (school margin)."""
        # Create teacher invoice
        teacher_invoice = Invoice.objects.create(
            invoice_type="teacher_payment",
            teacher=teacher_user,
            payment_balance=Decimal("0.00"),
            due_date=datetime.now() + timedelta(days=30),
            status="pending"
        )

        # Create student invoice for same lesson
        student_invoice = Invoice.objects.create(
            invoice_type="student_billing",
            student=student_user,
            payment_balance=Decimal("0.00"),
            due_date=datetime.now() + timedelta(days=30),
            status="pending"
        )

        # In-person lesson: teacher gets $50, student pays $100
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            teacher_rate=Decimal("50.00"),
            student_rate=Decimal("100.00"),
            duration=Decimal("1.0"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="in_person"
        )

        teacher_invoice.lessons.add(lesson)
        student_invoice.lessons.add(lesson)

        teacher_total = teacher_invoice.calculate_payment_balance()
        student_total = student_invoice.calculate_payment_balance()

        # Verify dual-rate system: student pays more than teacher receives
        assert teacher_total == Decimal("50.00")
        assert student_total == Decimal("100.00")
        assert student_total > teacher_total  # School keeps the difference

    def test_invoice_payment_balance_empty_invoice(self, teacher_user):
        """Test that empty invoice has zero balance."""
        invoice = Invoice.objects.create(
            invoice_type="teacher_payment",
            teacher=teacher_user,
            payment_balance=Decimal("0.00"),
            due_date=datetime.now() + timedelta(days=30),
            status="draft"
        )

        total = invoice.calculate_payment_balance()
        assert total == Decimal("0.00")
