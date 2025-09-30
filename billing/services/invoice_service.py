from .pdf_service import InvoicePDFGenerator
from .student_pdf_service import StudentInvoicePDFGenerator
from .email_service import InvoiceEmailService
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

class InvoiceProcessor:
    @staticmethod
    def generate_and_send_invoice(invoice, recipient_email=None):
        """
        Main orchestration function:
        1. Generate PDF with ReportLab
        2. Send email with PDF attachment
        
        Returns: (success: bool, message: str, pdf_content: bytes or None)
        """
        try:
            logger.info(f"Processing invoice {invoice.id} for teacher {invoice.teacher.get_full_name()}")
            
            # Step 1: Generate PDF
            pdf_generator = InvoicePDFGenerator(invoice)
            pdf_success, pdf_content = pdf_generator.generate_pdf()
            
            if not pdf_success:
                return False, "Failed to generate PDF", None
            
            # Step 2: Send email (only if PDF generation succeeded)
            email_success, email_message = InvoiceEmailService.send_invoice_email(
                invoice, pdf_content, recipient_email
            )
            
            if not email_success:
                return False, f"PDF generated but email failed: {email_message}", pdf_content
            
            logger.info(f"Successfully processed invoice {invoice.id}")
            return True, "Invoice generated and sent successfully", pdf_content
            
        except Exception as e:
            logger.error(f"Failed to process invoice {invoice.id}: {str(e)}")
            return False, f"Processing failed: {str(e)}", None
    
    @staticmethod
    def generate_and_send_combined_invoices(invoice, recipient_email=None):
        """
        Generate both teacher and student invoices and send them in one email:
        1. Generate teacher invoice PDF
        2. Generate student invoice PDFs (one per student)
        3. Send combined email with all PDFs
        
        Returns: (success: bool, message: str, teacher_pdf_content: bytes or None)
        """
        try:
            logger.info(f"Processing combined invoices for {invoice.id} - teacher {invoice.teacher.get_full_name()}")
            
            # Step 1: Generate teacher invoice PDF
            teacher_pdf_generator = InvoicePDFGenerator(invoice)
            teacher_pdf_success, teacher_pdf_content = teacher_pdf_generator.generate_pdf()
            
            if not teacher_pdf_success:
                return False, "Failed to generate teacher PDF", None
            
            # Step 2: Generate student invoice PDFs
            student_pdfs = {}
            
            # Group lessons by student
            lessons_by_student = defaultdict(list)
            for lesson in invoice.lessons.all():
                lessons_by_student[lesson.student].append(lesson)
            
            # Generate PDF for each student
            for student, student_lessons in lessons_by_student.items():
                try:
                    student_pdf_generator = StudentInvoicePDFGenerator(invoice, student_lessons)
                    student_pdf_success, student_pdf_content = student_pdf_generator.generate_pdf()
                    
                    if student_pdf_success:
                        student_pdfs[student.get_full_name()] = student_pdf_content
                        logger.info(f"Generated student invoice for {student.get_full_name()}")
                    else:
                        logger.warning(f"Failed to generate student invoice for {student.get_full_name()}")
                        
                except Exception as e:
                    logger.error(f"Error generating student invoice for {student.get_full_name()}: {str(e)}")
            
            # Step 3: Send combined email
            email_success, email_message = InvoiceEmailService.send_combined_invoices_email(
                invoice, teacher_pdf_content, student_pdfs, recipient_email
            )
            
            if not email_success:
                return False, f"PDFs generated but email failed: {email_message}", teacher_pdf_content
            
            logger.info(f"Successfully processed combined invoices for {invoice.id}")
            return True, f"Combined invoices generated and sent successfully ({len(student_pdfs)} student invoices)", teacher_pdf_content
            
        except Exception as e:
            logger.error(f"Failed to process combined invoices for {invoice.id}: {str(e)}")
            return False, f"Combined invoice processing failed: {str(e)}", None

