from django.core.mail import EmailMessage
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class InvoiceEmailService:
    @staticmethod
    def send_invoice_email(invoice, teacher_pdf_content, student_pdfs=None, recipient_email=None):
        """Send invoice email with teacher and student PDF attachments"""
        try:
            # Use provided recipient or get from database
            if recipient_email:
                # Single recipient provided - wrap in list
                email_recipients = [recipient_email]
            else:
                # Get all recipients from database
                from billing.models import InvoiceRecipientEmail, SystemSettings
                recipients = InvoiceRecipientEmail.objects.all()

                if recipients.exists():
                    email_recipients = list(recipients.values_list('email', flat=True))
                else:
                    # Fallback to SystemSettings if no recipients configured
                    system_settings = SystemSettings.get_settings()
                    email_recipients = [system_settings.invoice_recipient_email]

            # Count unique students
            student_count = len(student_pdfs) if student_pdfs else 0

            # Create email subject
            subject = f'New invoice submitted by {invoice.teacher.get_full_name()} for ${invoice.payment_balance:.2f}'
            if student_count > 0:
                subject += f' + {student_count} student invoice(s)'

            # Create email body
            body = f"""
Dear Management,

A new teacher invoice has been submitted for your review.

Teacher Invoice Details:
- Invoice ID: #{invoice.id}
- Teacher: {invoice.teacher.get_full_name()}
- Email: {invoice.teacher.email}
- Total Amount to Pay Teacher: ${invoice.payment_balance:.2f}
- Number of Lessons: {invoice.lessons.count()}

Attached Files:
- 1 Teacher Invoice 
"""

            if student_count > 0:
                body += f"- {student_count} Student Invoice(s) \n\n"
                body += "Student Invoices:\n"
                for student_pdf in student_pdfs:
                    student = student_pdf['student']
                    student_lessons = student_pdf['lessons']
                    student_total = sum(lesson.total_cost() for lesson in student_lessons)
                    body += f"  • {student.get_full_name()}: ${student_total:.2f} ({len(student_lessons)} lesson(s))\n"

            body += """
Please review and process accordingly.

Best regards,
Maple Key Music Academy
            """.strip()

            # Create email
            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@maplekey.com'),
                to=email_recipients,
            )

            # Attach teacher PDF
            teacher_name = invoice.teacher.get_full_name().lower().replace(' ', '_')
            email.attach(
                filename=f'TEACHER_{teacher_name}_invoice_{invoice.id}.pdf',
                content=teacher_pdf_content,
                mimetype='application/pdf'
            )

            # Attach student PDFs
            if student_pdfs:
                for student_pdf in student_pdfs:
                    student = student_pdf['student']
                    pdf_content = student_pdf['pdf_content']
                    student_name = student.get_full_name().lower().replace(' ', '_')
                    email.attach(
                        filename=f'STUDENT_{student_name}_invoice_{invoice.id}.pdf',
                        content=pdf_content,
                        mimetype='application/pdf'
                    )

            # Send email
            email.send()

            recipients_str = ', '.join(email_recipients)
            logger.info(f"Successfully sent invoice {invoice.id} with {student_count} student invoices to {recipients_str}")
            return True, f"Invoice sent successfully to {len(email_recipients)} recipient(s)"

        except Exception as e:
            logger.error(f"Failed to send invoice {invoice.id}: {str(e)}")
            return False, f"Failed to send email: {str(e)}"
