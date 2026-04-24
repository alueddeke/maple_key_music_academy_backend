"""
Teacher Paystub PDF Generator
Generates summary paystubs for teachers from MonthlyInvoiceBatch records.
"""
from decimal import Decimal
from reportlab.platypus import Paragraph, Spacer
from .invoicepdf_generator_base import BaseInvoicePDFGenerator
from .pdf_styles import get_invoice_styles
import logging

logger = logging.getLogger(__name__)


class TeacherPaystubPDFGenerator(BaseInvoicePDFGenerator):
    """
    Generate summary paystub PDF for teachers from MonthlyInvoiceBatch.
    Shows: period, teacher info, total payment, lesson count, school business info.
    """

    def __init__(self, batch):
        """Initialize with MonthlyInvoiceBatch instead of Invoice"""
        self.batch = batch
        # Call parent with batch as invoice (for buffer setup)
        super().__init__(batch)

    def generate_pdf(self):
        """
        Override base class to skip lesson details section.
        Paystubs show only summary info, not individual lesson breakdown.
        """
        try:
            # Create PDF document
            doc = self._create_document()

            # Build PDF content
            story = []

            # Get shared invoice styles
            pdf_styles = get_invoice_styles()

            # Build paystub sections (skip lessons table - this is a summary only)
            story.append(self._create_header(pdf_styles))
            story.append(self._create_divider())
            story.append(Spacer(1, 20))
            story.append(self._create_recipient_section(pdf_styles))
            story.append(Spacer(1, 25))

            # Skip lessons table section - paystubs are summaries only
            # Lesson count and total are already shown in the right column above

            story.append(Spacer(1, 25))
            story.append(self._create_notes_section(pdf_styles))

            # Build PDF
            doc.build(story)

            # Get PDF content
            pdf_content = self.buffer.getvalue()
            self.buffer.close()

            logger.info(f"Successfully generated paystub PDF for batch {self.batch.id}")
            return True, pdf_content

        except Exception as e:
            logger.error(f"Failed to generate paystub PDF for batch {self.batch.id}: {str(e)}")
            self.buffer.close()
            return False, None

    def get_invoice_title(self):
        """Return 'PAYSTUB' as the title"""
        return 'PAYSTUB'

    def get_left_column_heading(self):
        """Return 'TEACHER INFORMATION' as left column heading"""
        return 'TEACHER INFORMATION'

    def get_left_column_content(self, pdf_styles):
        """Return teacher information for left column"""
        teacher = self.batch.teacher
        content = [
            Paragraph(f"<b>{self.get_left_column_heading()}</b>", pdf_styles['heading_style']),
            Paragraph(teacher.get_full_name(), pdf_styles['normal_style']),
        ]

        if teacher.email:
            content.append(Paragraph(teacher.email, pdf_styles['normal_style']))

        if teacher.phone_number:
            content.append(Paragraph(teacher.phone_number, pdf_styles['normal_style']))

        if teacher.address:
            # Split multi-line address
            address_lines = teacher.address.split('\n')
            for line in address_lines:
                content.append(Paragraph(line, pdf_styles['normal_style']))

        return content

    def get_right_column_content(self, pdf_styles):
        """Return paystub details for right column"""
        from datetime import datetime

        # Format period as "Month YYYY"
        month_names = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                       'July', 'August', 'September', 'October', 'November', 'December']
        period = f"{month_names[self.batch.month]} {self.batch.year}"

        # Calculate total payment
        total_payment = self.calculate_total_payment()

        # Get lesson count
        lesson_count = self.batch.lesson_items.filter(status='completed').count()

        content = [
            Paragraph(f"<b>Paystub Number:</b> {self.batch.batch_number}", pdf_styles['normal_style']),
            Paragraph(f"<b>Period:</b> {period}", pdf_styles['normal_style']),
            Paragraph(f"<b>Lessons Completed:</b> {lesson_count}", pdf_styles['normal_style']),
            Paragraph(f"<b>Total Amount (CAD):</b> ${total_payment:.2f}", pdf_styles['normal_style']),
        ]

        # Payment method and payment date removed - will be added in future when management can record payments

        return content

    def get_lessons_table_header(self):
        """Return None - we don't show detailed lessons table for paystub"""
        return None

    def get_lessons_data(self):
        """Return None - we don't show detailed lessons for paystub"""
        return None

    def format_lesson_row(self, lesson, pdf_styles):
        """Not used for paystub - return None"""
        return None

    def get_total_amount(self):
        """Return total payment amount for this batch"""
        return self.calculate_total_payment()

    def get_totals_table_rows(self):
        """Return summary totals table data"""
        total_payment = self.calculate_total_payment()
        lesson_count = self.batch.lesson_items.filter(status='completed').count()

        return [
            ['', '', 'Lessons Completed:', str(lesson_count)],
            ['', '', 'Total Payment (CAD):', f"${total_payment:.2f}"],
        ]

    def get_notes_text(self):
        """Return school business information for footer"""
        school = self.batch.school

        notes_parts = ["<b>School Business Information</b><br/>"]

        if school:
            notes_parts.append(f"{school.name}<br/>")

            # Build address
            address_parts = []
            if school.street_address:
                address_parts.append(school.street_address)
            if school.city:
                address_parts.append(school.city)
            if school.province:
                address_parts.append(school.province)
            if school.postal_code:
                address_parts.append(school.postal_code)

            if address_parts:
                notes_parts.append(', '.join(address_parts) + '<br/>')

            # Add tax/business number if available
            if school.tax_number:
                notes_parts.append(f"Business Number: {school.tax_number}<br/>")

        notes_parts.append("<br/>This paystub is for your tax records.")

        return ''.join(notes_parts)

    def calculate_total_payment(self):
        """Calculate total teacher payment from completed lessons"""
        from decimal import Decimal
        total = sum(
            item.calculate_teacher_payment()
            for item in self.batch.lesson_items.all()
        )
        return total if total else Decimal('0.00')
