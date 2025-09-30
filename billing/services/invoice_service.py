from .pdf_service import InvoicePDFGenerator
from .email_service import InvoiceEmailService
import logging

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

