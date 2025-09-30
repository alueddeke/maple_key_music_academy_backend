# Email Configuration for PDF Invoice Testing

## Setup Instructions

### 1. Create a `.env` file in the backend directory

Create a `.env` file in `/maple_key_music_academy_backend/` with the following content:

```env
# Django Settings
SECRET_KEY=your-secret-key-here
DEBUG=True

# Database Settings
POSTGRES_DB=maple_key_dev
POSTGRES_USER=maple_key_user
POSTGRES_PASSWORD=maple_key_password
POSTGRES_HOST=db
POSTGRES_PORT=5432

# Google OAuth Settings
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Email Settings for Testing
EMAIL_HOST_USER=antonilueddeke@gmail.com
EMAIL_HOST_PASSWORD=your-app-password-here
DEFAULT_FROM_EMAIL=antonilueddeke@gmail.com
TEST_EMAIL_RECIPIENT=antonilueddeke@gmail.com
```

### 2. Gmail App Password Setup

To send emails through Gmail, you need to:

1. **Enable 2-Factor Authentication** on your Gmail account
2. **Generate an App Password**:
   - Go to Google Account settings
   - Security → 2-Step Verification → App passwords
   - Generate a new app password for "Mail"
   - Use this password in `EMAIL_HOST_PASSWORD` in your `.env` file

### 3. Test Email Configuration

The system is configured to send test emails to `antonilueddeke@gmail.com` by default.

To change the test email recipient, update the `TEST_EMAIL_RECIPIENT` value in your `.env` file:

```env
TEST_EMAIL_RECIPIENT=your-test-email@gmail.com
```

### 4. Testing the Email Integration

Once configured, when you submit lessons for an invoice:

1. The system will generate a PDF invoice
2. Send it as an email attachment to the configured test email
3. You can download and view the PDF to see how it looks

### 5. Email Content

The email will include:
- Subject: "New invoice submitted by [Teacher Name] for $[Amount]"
- Body: Invoice details and summary
- Attachment: PDF file named `[teachername]_invoice_[id].pdf`

## Troubleshooting

- **Authentication Error**: Make sure you're using an App Password, not your regular Gmail password
- **Connection Error**: Check that Gmail SMTP settings are correct (smtp.gmail.com, port 587, TLS)
- **No Email Received**: Check spam folder and verify the email address is correct
