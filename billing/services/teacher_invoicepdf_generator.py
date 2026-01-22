import io
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
import logging
from collections import defaultdict
from .invoicepdf_generator_base import BaseInvoicePDFGenerator
from .student_invoicepdf_generator import StudentInvoicePDFGenerator
from .email_service import InvoiceEmailService

logger = logging.getLogger(__name__)


class TeacherInvoicePDFGenerator(BaseInvoicePDFGenerator):
    """Generate teacher payment invoice PDF"""

    def get_invoice_title(self):
        return "TEACHER INVOICE"

    def get_left_column_heading(self):
        return "TEACHER INFORMATION"

    def get_left_column_content(self, pdf_styles):
        """Teacher information section"""
        left_column = []
        teacher = self.invoice.teacher

        left_column.append(Paragraph(self.get_left_column_heading(), pdf_styles['heading_style']))
        left_column.append(Paragraph(f"<b>{teacher.get_full_name()}</b>", pdf_styles['normal_style']))
        left_column.append(Paragraph(f"{teacher.email}", pdf_styles['normal_style']))

        if teacher.phone_number:
            left_column.append(Paragraph(f"{teacher.phone_number}", pdf_styles['normal_style']))

        if teacher.address:
            address_lines = teacher.address.replace(',', '<br/>').replace('\n', '<br/>')
            left_column.append(Paragraph(address_lines, pdf_styles['normal_style']))

        return left_column

    def get_right_column_content(self, pdf_styles):
        """Invoice details for teacher"""
        right_column = []
        right_align_style = ParagraphStyle('RightAlign', parent=pdf_styles['normal_style'], alignment=TA_RIGHT)
        right_align_bold = ParagraphStyle('RightAlignBold', parent=pdf_styles['bold_style'], alignment=TA_RIGHT)

        right_column.append(Paragraph(f"<b>Invoice Number:</b> {self.invoice.id}", right_align_style))
        right_column.append(Paragraph(f"<b>Invoice Date:</b> {self.invoice.created_at.strftime('%B %d, %Y')}", right_align_style))
        right_column.append(Paragraph(f"<b>Total Amount (CAD):</b> ${self.invoice.payment_balance:.2f}", right_align_bold))

        return right_column

    def get_lessons_table_header(self):
        return ['Student Name', 'Date', 'Duration (hrs)', 'Total ($)']

    def get_lessons_data(self):
        return self.invoice.lessons.all()

    def format_lesson_row(self, lesson, pdf_styles):
        lesson_date = lesson.scheduled_date.strftime('%Y-%m-%d') if lesson.scheduled_date else 'N/A'

        return [
            Paragraph(lesson.student.get_full_name(), pdf_styles['normal_style']),
            lesson_date,
            f"{lesson.duration:.2f}",
            f"${lesson.total_cost():.2f}"  # Uses teacher_rate
        ]

    def get_total_amount(self):
        return self.invoice.payment_balance

    def get_totals_table_rows(self):
        return [
            ['', '', 'TOTAL:', f"${self.invoice.payment_balance:.2f}"]
        ]

    def get_notes_text(self):
        return "Thank you for your service!"


class InvoiceProcessor:
    """Orchestrates invoice PDF generation and email sending"""

    @staticmethod
    def generate_and_send_invoice(invoice, recipient_email=None):
        """
        Main orchestration function:
        1. Generate teacher PDF with ReportLab
        2. Generate student PDFs for each student
        3. Send email with all PDF attachments

        Returns: (success: bool, message: str, pdf_content: bytes or None)
        """
        try:
            logger.info(f"Processing invoice {invoice.id} for teacher {invoice.teacher.get_full_name()}")

            # Step 1: Generate teacher PDF
            pdf_generator = TeacherInvoicePDFGenerator(invoice)
            teacher_pdf_success, teacher_pdf_content = pdf_generator.generate_pdf()

            if not teacher_pdf_success:
                return False, "Failed to generate teacher PDF", None

            # Step 2: Generate student PDFs
            # Group lessons by student
            lessons_by_student = defaultdict(list)
            for lesson in invoice.lessons.all():
                lessons_by_student[lesson.student].append(lesson)

            student_pdfs = []
            for student, student_lessons in lessons_by_student.items():
                student_pdf_generator = StudentInvoicePDFGenerator(invoice, student_lessons)
                student_pdf_success, student_pdf_content = student_pdf_generator.generate_pdf()

                if student_pdf_success:
                    student_pdfs.append({
                        'student': student,
                        'pdf_content': student_pdf_content,
                        'lessons': student_lessons
                    })
                else:
                    logger.warning(f"Failed to generate PDF for student {student.get_full_name()}")

            # Step 3: Send email with all PDFs
            email_success, email_message = InvoiceEmailService.send_invoice_email(
                invoice, teacher_pdf_content, student_pdfs, recipient_email
            )

            if not email_success:
                return False, f"PDFs generated but email failed: {email_message}", teacher_pdf_content

            logger.info(f"Successfully processed invoice {invoice.id} with {len(student_pdfs)} student invoices")
            return True, "Invoice generated and sent successfully", teacher_pdf_content

        except Exception as e:
            logger.error(f"Failed to process invoice {invoice.id}: {str(e)}")
            return False, f"Processing failed: {str(e)}", None
