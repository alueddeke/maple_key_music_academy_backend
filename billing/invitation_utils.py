"""Utilities for managing invitation tokens and sending invitation emails"""
import secrets
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from .models import InvitationToken, ApprovedEmail


def generate_invitation_token(approved_email: ApprovedEmail) -> InvitationToken:
    """
    Generate a secure invitation token for a pre-approved email

    Args:
        approved_email: ApprovedEmail instance

    Returns:
        InvitationToken instance
    """
    # Generate secure random token
    token = secrets.token_urlsafe(32)

    # Token expires in 48 hours
    expires_at = timezone.now() + timedelta(hours=48)

    # Create invitation token
    invitation = InvitationToken.objects.create(
        email=approved_email.email,
        token=token,
        user_type=approved_email.user_type,
        approved_email=approved_email,
        expires_at=expires_at
    )

    return invitation


def send_invitation_email(invitation: InvitationToken) -> tuple[bool, str]:
    """
    Send invitation email to the user

    Args:
        invitation: InvitationToken instance

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Build invitation URL
        frontend_url = settings.FRONTEND_URL or 'http://localhost:5173'
        invitation_url = f"{frontend_url}/invite/{invitation.token}"

        # Email subject
        subject = 'Welcome to Maple Key Music Academy - Set Up Your Account'

        # Email body
        message = f"""
Hello!

You've been invited to join Maple Key Music Academy as a {invitation.get_user_type_display()}.

To set up your account, please click the link below:

{invitation_url}

On the account setup page, you can:
- Set a password for email/password login
- Or sign in with your Google account

This invitation link will expire in 48 hours.

If you have any questions, please contact the academy management.

Best regards,
Maple Key Music Academy Team

---
Maple Key Music Academy
This is a one-time invitation email. You will not receive further emails until you create your account.
Contact: {frontend_url}/contact
"""

        # HTML version (optional)
        html_message = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <h2 style="color: #2563eb;">Welcome to Maple Key Music Academy!</h2>

    <p>You've been invited to join as a <strong>{invitation.get_user_type_display()}</strong>.</p>

    <p>To set up your account, please click the button below:</p>

    <div style="margin: 30px 0;">
        <a href="{invitation_url}"
           style="background-color: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block;">
            Set Up Your Account
        </a>
    </div>

    <p style="color: #666; font-size: 14px;">Or copy and paste this link into your browser:</p>
    <p style="background-color: #f3f4f6; padding: 10px; border-radius: 4px; word-break: break-all;">
        {invitation_url}
    </p>

    <p style="margin-top: 30px;">On the account setup page, you can:</p>
    <ul>
        <li>Set a password for email/password login</li>
        <li>Or sign in with your Google account</li>
    </ul>

    <p style="color: #ef4444; font-size: 14px;">
        <strong>Note:</strong> This invitation link will expire in 48 hours.
    </p>

    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">

    <p style="color: #666; font-size: 12px;">
        If you have any questions, please contact the academy management.<br>
        Best regards,<br>
        Maple Key Music Academy Team
    </p>

    <p style="color: #999; font-size: 11px; margin-top: 20px;">
        Maple Key Music Academy<br>
        This is a one-time invitation email. You will not receive further emails until you create your account.<br>
        <a href="{frontend_url}/contact" style="color: #999;">Contact Us</a>
    </p>
</body>
</html>
"""

        # Send email
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            html_message=html_message,
            fail_silently=False,
        )

        return True, "Invitation email sent successfully"

    except Exception as e:
        return False, f"Failed to send email: {str(e)}"


def create_and_send_invitation(approved_email: ApprovedEmail) -> tuple[bool, str, InvitationToken | None]:
    """
    Create invitation token and send email (combined operation)

    Args:
        approved_email: ApprovedEmail instance

    Returns:
        Tuple of (success: bool, message: str, invitation: InvitationToken | None)
    """
    try:
        # Generate token
        invitation = generate_invitation_token(approved_email)

        # Send email
        email_success, email_message = send_invitation_email(invitation)

        if email_success:
            return True, "Invitation created and sent successfully", invitation
        else:
            return False, f"Invitation created but email failed: {email_message}", invitation

    except Exception as e:
        return False, f"Failed to create invitation: {str(e)}", None
