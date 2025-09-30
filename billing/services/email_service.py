from django.core.mail import EmailMessage
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class InvoiceEmailService:
    @staticmethod
    def send_invoice_email(invoice, pdf_content, recipient_email=None):
        """Send invoice email with PDF attachment"""
        try:
            # Use provided recipient or default to a.lueddeke@hotmail.com
            email_recipient = recipient_email or 'a.lueddeke@hotmail.com'
            
            # Create email subject
            subject = f'New invoice submitted by {invoice.teacher.get_full_name()} for ${invoice.payment_balance:.2f}'
            
            # Create email body
            body = f"""
Dear Management,

A new teacher invoice has been submitted for your review.

Invoice Details:
- Invoice ID: #{invoice.id}
- Teacher: {invoice.teacher.get_full_name()}
- Email: {invoice.teacher.email}
- Total Amount: ${invoice.payment_balance:.2f}
- Number of Lessons: {invoice.lessons.count()}

Please find the detailed invoice attached as a PDF.

Best regards,
Maple Key Music Academy System
            """.strip()
            
            # Create email
            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@maplekey.com'),
                to=[email_recipient],
            )
            
            # Attach PDF
            teacher_name = invoice.teacher.get_full_name().lower().replace(' ', '')
            email.attach(
                filename=f'{teacher_name}_invoice_{invoice.id}.pdf',
                content=pdf_content,
                mimetype='application/pdf'
            )
            
            # Send email
            email.send()
            
            logger.info(f"Successfully sent invoice {invoice.id} to {email_recipient}")
            return True, f"Invoice sent successfully to {email_recipient}"
            
        except Exception as e:
            logger.error(f"Failed to send invoice {invoice.id}: {str(e)}")
            return False, f"Failed to send email: {str(e)}"
