from .pdf_service import InvoicePDFGenerator
from .student_pdf_service import StudentInvoicePDFGenerator
from .email_service import InvoiceEmailService
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

class InvoiceProcessor:
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
            pdf_generator = InvoicePDFGenerator(invoice)
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
