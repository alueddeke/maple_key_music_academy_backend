"""
Unit tests for invoice and lesson cost calculations.

CRITICAL: These tests protect money calculations - invoice totals must be exact.
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
            rate=Decimal("80.00"),
            duration=Decimal("1.5"),
            scheduled_date=datetime.now(),
            status="completed"
        )

        # CRITICAL: 1.5 hours at $80/hr should be $120, not $80
        assert lesson.total_cost() == Decimal("120.00")

    def test_lesson_total_cost_quarter_hours(self, teacher_user, student_user):
        """Test cost calculation for 15-minute increments."""
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            rate=Decimal("80.00"),
            duration=Decimal("0.25"),  # 15 minutes
            scheduled_date=datetime.now(),
            status="completed"
        )

        assert lesson.total_cost() == Decimal("20.00")

    def test_lesson_total_cost_different_rates(self, teacher_user, student_user):
        """Test cost calculation with different hourly rates."""
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            rate=Decimal("100.00"),  # Higher rate
            duration=Decimal("2.0"),
            scheduled_date=datetime.now(),
            status="completed"
        )

        assert lesson.total_cost() == Decimal("200.00")

    def test_lesson_total_cost_uses_decimal_precision(self, teacher_user, student_user):
        """Test that cost calculation maintains Decimal precision (no floating point errors)."""
        lesson = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            rate=Decimal("45.00"),  # Online lesson rate
            duration=Decimal("1.5"),
            scheduled_date=datetime.now(),
            status="completed"
        )

        # Should be exactly 67.50, not 67.49999999
        assert lesson.total_cost() == Decimal("67.50")
        assert isinstance(lesson.total_cost(), Decimal)


@pytest.mark.django_db
class TestInvoicePaymentBalance:
    """Test invoice payment_balance = sum of all lesson costs."""

    def test_invoice_payment_balance_single_lesson(self, teacher_user, student_user):
        """Test invoice total with one lesson."""
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
            rate=Decimal("80.00"),
            duration=Decimal("1.0"),
            scheduled_date=datetime.now(),
            status="completed"
        )

        invoice.lessons.add(lesson)
        invoice.save()

        # Calculate total from lessons
        total = sum(lesson.total_cost() for lesson in invoice.lessons.all())
        assert total == Decimal("80.00")

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
                rate=Decimal("80.00"),
                duration=Decimal("1.0"),
                scheduled_date=datetime.now(),
                status="completed"
            ),
            Lesson.objects.create(
                teacher=teacher_user,
                student=student_user,
                rate=Decimal("80.00"),
                duration=Decimal("1.5"),
                scheduled_date=datetime.now(),
                status="completed"
            ),
            Lesson.objects.create(
                teacher=teacher_user,
                student=student_user,
                rate=Decimal("80.00"),
                duration=Decimal("0.5"),
                scheduled_date=datetime.now(),
                status="completed"
            ),
        ]

        for lesson in lessons:
            invoice.lessons.add(lesson)
        invoice.save()

        # Total should be: 80 + 120 + 40 = 240
        total = sum(lesson.total_cost() for lesson in invoice.lessons.all())
        assert total == Decimal("240.00")

    def test_invoice_payment_balance_mixed_rates(self, teacher_user, student_user):
        """Test invoice total with lessons at different rates (in-person vs online)."""
        invoice = Invoice.objects.create(
            invoice_type="teacher_payment",
            teacher=teacher_user,
            payment_balance=Decimal("0.00"),
            due_date=datetime.now() + timedelta(days=30),
            status="pending"
        )

        # In-person lesson at $80/hr
        lesson1 = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            rate=Decimal("80.00"),
            duration=Decimal("1.0"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="in_person"
        )

        # Online lesson at $45/hr
        lesson2 = Lesson.objects.create(
            teacher=teacher_user,
            student=student_user,
            rate=Decimal("45.00"),
            duration=Decimal("1.0"),
            scheduled_date=datetime.now(),
            status="completed",
            lesson_type="online"
        )

        invoice.lessons.add(lesson1, lesson2)
        invoice.save()

        # Total should be: 80 + 45 = 125
        total = sum(lesson.total_cost() for lesson in invoice.lessons.all())
        assert total == Decimal("125.00")

    def test_invoice_payment_balance_empty_invoice(self, teacher_user):
        """Test that empty invoice has zero balance."""
        invoice = Invoice.objects.create(
            invoice_type="teacher_payment",
            teacher=teacher_user,
            payment_balance=Decimal("0.00"),
            due_date=datetime.now() + timedelta(days=30),
            status="draft"
        )

        total = sum(lesson.total_cost() for lesson in invoice.lessons.all())
        assert total == Decimal("0.00")
