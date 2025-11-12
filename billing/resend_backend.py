"""Custom Django email backend using Resend HTTP API"""
import resend
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class ResendEmailBackend(BaseEmailBackend):
    """
    Email backend that uses Resend's HTTP API instead of SMTP.
    This avoids issues with blocked SMTP ports (587, 465).
    """

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        # Set Resend API key
        resend.api_key = getattr(settings, 'RESEND_API_KEY', None)
        if not resend.api_key:
            if not self.fail_silently:
                raise ValueError("RESEND_API_KEY setting is required for ResendEmailBackend")

    def send_messages(self, email_messages):
        """
        Send one or more EmailMessage objects and return the number of email
        messages sent.
        """
        if not email_messages:
            return 0

        num_sent = 0
        for message in email_messages:
            try:
                sent = self._send(message)
                if sent:
                    num_sent += 1
            except Exception as e:
                if not self.fail_silently:
                    raise
        return num_sent

    def _send(self, message):
        """Send a single email message using Resend API"""
        if not message.recipients():
            return False

        try:
            # Prepare email parameters for Resend API
            params = {
                "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
                "to": message.to,
                "subject": message.subject,
            }

            # Add CC and BCC if present
            if message.cc:
                params["cc"] = message.cc
            if message.bcc:
                params["bcc"] = message.bcc

            # Add reply_to if present
            if message.reply_to:
                params["reply_to"] = message.reply_to

            # Handle both plain text and HTML content
            if message.content_subtype == 'html':
                params["html"] = message.body
            else:
                params["text"] = message.body

            # If there are alternatives (like HTML version of plain text), use them
            # Note: Only EmailMultiAlternatives has .alternatives, not EmailMessage
            if hasattr(message, 'alternatives') and message.alternatives:
                for alternative in message.alternatives:
                    content, mimetype = alternative
                    if mimetype == 'text/html':
                        params["html"] = content

            # Send via Resend API
            response = resend.Emails.send(params)

            return True

        except Exception as e:
            if not self.fail_silently:
                raise
            return False
