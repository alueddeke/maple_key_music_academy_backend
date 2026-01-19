import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
import logging
from datetime import datetime, timedelta
from .invoicepdf_generator_base import BaseInvoicePDFGenerator

logger = logging.getLogger(__name__)


class StudentInvoicePDFGenerator(BaseInvoicePDFGenerator):
    """Generate student billing invoice PDF"""

    def __init__(self, invoice, student_lessons):
        super().__init__(invoice)
        self.student_lessons = student_lessons

    def get_invoice_title(self):
        return "INVOICE"

    def get_left_column_heading(self):
        return "BILL TO"

    def get_left_column_content(self, pdf_styles):
        """Bill To section"""
        left_column = []
        student = self.student_lessons[0].student if self.student_lessons else None

        left_column.append(Paragraph(self.get_left_column_heading(), pdf_styles['heading_style']))

        if student:
            left_column.append(Paragraph(f"<b>{student.get_full_name()}</b>", pdf_styles['normal_style']))
            left_column.append(Paragraph(f"{student.get_full_name()}", pdf_styles['normal_style']))

            if student.address:
                address_lines = student.address.replace(',', '<br/>').replace('\n', '<br/>')
                left_column.append(Paragraph(address_lines, pdf_styles['normal_style']))

            if student.phone_number:
                left_column.append(Paragraph(f"{student.phone_number}", pdf_styles['normal_style']))

            if student.email:
                left_column.append(Paragraph(f"{student.email}", pdf_styles['normal_style']))

        return left_column

    def get_right_column_content(self, pdf_styles):
        """Invoice details for student"""
        right_column = []
        due_date = datetime.now() + timedelta(days=14)
        student_total = self.get_total_amount()

        right_align_style = ParagraphStyle('RightAlign', parent=pdf_styles['normal_style'], alignment=TA_RIGHT)
        right_align_bold = ParagraphStyle('RightAlignBold', parent=pdf_styles['bold_style'], alignment=TA_RIGHT)

        right_column.append(Paragraph(f"<b>Invoice Number:</b> {self.invoice.id}", right_align_style))
        right_column.append(Paragraph(f"<b>Invoice Date:</b> {datetime.now().strftime('%B %d, %Y')}", right_align_style))
        right_column.append(Paragraph(f"<b>Payment Due:</b> {due_date.strftime('%B %d, %Y')}", right_align_bold))
        right_column.append(Paragraph(f"<b>Amount Due (CAD):</b> ${student_total:.2f}", right_align_bold))

        return right_column

    def get_lessons_table_header(self):
        return ['Description', 'Date', 'Duration (hrs)', 'Amount']

    def get_lessons_data(self):
        return self.student_lessons

    def format_lesson_row(self, lesson, pdf_styles):
        lesson_date = lesson.scheduled_date.strftime('%Y-%m-%d') if lesson.scheduled_date else 'N/A'
        lesson_type_label = 'Online Lesson' if lesson.lesson_type == 'online' else 'Music Lesson'

        return [
            Paragraph(f"<b>{lesson_type_label}</b>", pdf_styles['normal_style']),
            lesson_date,
            f"{lesson.duration:.2f}",
            f"${lesson.student_cost():.2f}"  # Uses student_rate
        ]

    def get_total_amount(self):
        return sum(lesson.student_cost() for lesson in self.student_lessons)

    def get_totals_table_rows(self):
        student_total = self.get_total_amount()
        return [
            ['', '', 'Total:', f"${student_total:.2f}"],
            ['', '', 'Amount Due (CAD):', f"${student_total:.2f}"]
        ]

    def get_notes_text(self):
        return "E-Transfer - maplekeymusic.academy@gmail.com"
