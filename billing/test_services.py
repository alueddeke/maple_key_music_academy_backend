import os
import django
from django.conf import settings

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maple_key_backend.settings')
django.setup()

import pytest
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch, MagicMock
from rest_framework.test import APITestCase
from rest_framework import status
from datetime import datetime, timedelta
from django.core.exceptions import ValidationError

from billing.models import Lesson, Invoice
from custom_auth.decorators import teacher_required

User = get_user_model()


class PDFServiceTests(TestCase):
    """Unit tests for PDF generation service"""
    
    def setUp(self):
        """Set up test data for PDF service tests"""
        self.teacher = User.objects.create_user(
            email='teacher@test.com',
            password='testpass123',
            first_name='John',
            last_name='Teacher',
            user_type='teacher',
            hourly_rate=75.00,
            phone_number='(555) 123-4567',
            address='123 Music St, City, State 12345',
            is_approved=True
        )
        
        self.student1 = User.objects.create_user(
            email='student1@test.com',
            password='testpass123',
            first_name='Alice',
            last_name='Johnson',
            user_type='student',
            is_approved=True
        )
        
        self.student2 = User.objects.create_user(
            email='student2@test.com',
            password='testpass123',
            first_name='Bob',
            last_name='Smith',
            user_type='student',
            is_approved=True
        )
        
        # Create lessons
        self.lesson1 = Lesson.objects.create(
            teacher=self.teacher,
            student=self.student1,
            scheduled_date=timezone.now(),
            duration=1.0,
            rate=75.00,
            status='completed'
        )
        
        self.lesson2 = Lesson.objects.create(
            teacher=self.teacher,
            student=self.student2,
            scheduled_date=timezone.now(),
            duration=1.5,
            rate=75.00,
            status='completed'
        )
        
        # Create invoice
        self.invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=self.teacher,
            status='pending',
            created_by=self.teacher,
            payment_balance=0
        )
        
        # Add lessons to invoice
        self.invoice.lessons.set([self.lesson1, self.lesson2])
        self.invoice.payment_balance = self.invoice.calculate_payment_balance()
        self.invoice.save()

    def test_pdf_generation_success(self):
        """Test successful PDF generation"""
        from billing.services.pdf_service import InvoicePDFGenerator
        
        pdf_generator = InvoicePDFGenerator(self.invoice)
        success, pdf_content = pdf_generator.generate_pdf()
        
        self.assertTrue(success)
        self.assertIsNotNone(pdf_content)
        self.assertGreater(len(pdf_content), 0)
        
        # Verify PDF content is valid (starts with PDF header)
        self.assertTrue(pdf_content.startswith(b'%PDF'))

    def test_pdf_generation_with_no_lessons(self):
        """Test PDF generation with invoice that has no lessons"""
        from billing.services.pdf_service import InvoicePDFGenerator
        
        # Create invoice without lessons
        empty_invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=self.teacher,
            status='pending',
            created_by=self.teacher,
            payment_balance=0
        )
        
        pdf_generator = InvoicePDFGenerator(empty_invoice)
        success, pdf_content = pdf_generator.generate_pdf()
        
        self.assertTrue(success)
        self.assertIsNotNone(pdf_content)
        self.assertGreater(len(pdf_content), 0)

    def test_pdf_generation_with_teacher_info(self):
        """Test PDF generation includes teacher information"""
        from billing.services.pdf_service import InvoicePDFGenerator
        
        pdf_generator = InvoicePDFGenerator(self.invoice)
        success, pdf_content = pdf_generator.generate_pdf()
        
        self.assertTrue(success)
        self.assertIsNotNone(pdf_content)

    def test_pdf_generation_with_lesson_breakdown(self):
        """Test PDF generation includes lesson breakdown"""
        from billing.services.pdf_service import InvoicePDFGenerator
        
        pdf_generator = InvoicePDFGenerator(self.invoice)
        success, pdf_content = pdf_generator.generate_pdf()
        
        self.assertTrue(success)
        self.assertIsNotNone(pdf_content)

    def test_pdf_generation_with_different_rates(self):
        """Test PDF generation with lessons having different rates"""
        from billing.services.pdf_service import InvoicePDFGenerator
        
        # Create lesson with different rate
        lesson3 = Lesson.objects.create(
            teacher=self.teacher,
            student=self.student1,
            scheduled_date=timezone.now(),
            duration=0.5,
            rate=100.00,  # Different rate
            status='completed'
        )
        
        # Add to invoice
        self.invoice.lessons.add(lesson3)
        self.invoice.payment_balance = self.invoice.calculate_payment_balance()
        self.invoice.save()
        
        pdf_generator = InvoicePDFGenerator(self.invoice)
        success, pdf_content = pdf_generator.generate_pdf()
        
        self.assertTrue(success)
        self.assertIsNotNone(pdf_content)

    def test_pdf_generation_with_missing_teacher_info(self):
        """Test PDF generation with teacher missing optional info"""
        from billing.services.pdf_service import InvoicePDFGenerator
        
        # Create teacher without phone and address
        teacher_no_info = User.objects.create_user(
            email='teacher2@test.com',
            password='testpass123',
            first_name='Jane',
            last_name='Teacher',
            user_type='teacher',
            hourly_rate=65.00,
            is_approved=True
        )
        
        invoice_no_info = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=teacher_no_info,
            status='pending',
            created_by=teacher_no_info,
            payment_balance=0
        )
        
        pdf_generator = InvoicePDFGenerator(invoice_no_info)
        success, pdf_content = pdf_generator.generate_pdf()
        
        self.assertTrue(success)
        self.assertIsNotNone(pdf_content)


class EmailServiceTests(TestCase):
    """Unit tests for email service"""
    
    def setUp(self):
        """Set up test data for email service tests"""
        self.teacher = User.objects.create_user(
            email='teacher@test.com',
            password='testpass123',
            first_name='John',
            last_name='Teacher',
            user_type='teacher',
            hourly_rate=75.00,
            is_approved=True
        )
        
        self.student = User.objects.create_user(
            email='student@test.com',
            password='testpass123',
            first_name='Alice',
            last_name='Johnson',
            user_type='student',
            is_approved=True
        )
        
        # Create lesson and invoice
        self.lesson = Lesson.objects.create(
            teacher=self.teacher,
            student=self.student,
            scheduled_date=timezone.now(),
            duration=1.0,
            rate=75.00,
            status='completed'
        )
        
        self.invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=self.teacher,
            status='pending',
            created_by=self.teacher,
            payment_balance=75.00
        )
        
        self.invoice.lessons.set([self.lesson])

    @patch('billing.services.email_service.EmailMessage')
    def test_send_invoice_email_success(self, mock_email_message):
        """Test successful email sending"""
        from billing.services.email_service import InvoiceEmailService
        
        # Mock the email message
        mock_email_instance = MagicMock()
        mock_email_message.return_value = mock_email_instance
        
        # Mock PDF content
        pdf_content = b'fake pdf content'
        
        success, message = InvoiceEmailService.send_invoice_email(
            self.invoice, pdf_content
        )
        
        self.assertTrue(success)
        self.assertIn('sent successfully', message)
        
        # Verify email was created with correct parameters
        mock_email_message.assert_called_once()
        call_args = mock_email_message.call_args
        
        # Check subject contains teacher name and amount
        self.assertIn(self.teacher.get_full_name(), call_args[1]['subject'])
        self.assertIn('$75.00', call_args[1]['subject'])
        
        # Check recipient
        self.assertEqual(call_args[1]['to'], ['a.lueddeke@hotmail.com'])
        
        # Verify email was sent
        mock_email_instance.send.assert_called_once()

    @patch('billing.services.email_service.EmailMessage')
    def test_send_invoice_email_with_custom_recipient(self, mock_email_message):
        """Test email sending with custom recipient"""
        from billing.services.email_service import InvoiceEmailService
        
        # Mock the email message
        mock_email_instance = MagicMock()
        mock_email_message.return_value = mock_email_instance
        
        pdf_content = b'fake pdf content'
        custom_recipient = 'custom@test.com'
        
        success, message = InvoiceEmailService.send_invoice_email(
            self.invoice, pdf_content, custom_recipient
        )
        
        self.assertTrue(success)
        
        # Verify custom recipient was used
        call_args = mock_email_message.call_args
        self.assertEqual(call_args[1]['to'], [custom_recipient])

    @patch('billing.services.email_service.EmailMessage')
    def test_send_invoice_email_attachment(self, mock_email_message):
        """Test email includes PDF attachment"""
        from billing.services.email_service import InvoiceEmailService
        
        # Mock the email message
        mock_email_instance = MagicMock()
        mock_email_message.return_value = mock_email_instance
        
        pdf_content = b'fake pdf content'
        
        InvoiceEmailService.send_invoice_email(self.invoice, pdf_content)
        
        # Verify attachment was added
        mock_email_instance.attach.assert_called_once()
        attach_args = mock_email_instance.attach.call_args
        
        # Check attachment parameters
        expected_filename = f'{self.teacher.get_full_name().lower().replace(" ", "")}_invoice_{self.invoice.id}.pdf'
        self.assertEqual(attach_args[1]['filename'], expected_filename)
        self.assertEqual(attach_args[1]['content'], pdf_content)
        self.assertEqual(attach_args[1]['mimetype'], 'application/pdf')

    @patch('billing.services.email_service.EmailMessage')
    def test_send_invoice_email_failure(self, mock_email_message):
        """Test email sending failure handling"""
        from billing.services.email_service import InvoiceEmailService
        
        # Mock email to raise exception
        mock_email_message.side_effect = Exception("SMTP Error")
        
        pdf_content = b'fake pdf content'
        
        success, message = InvoiceEmailService.send_invoice_email(
            self.invoice, pdf_content
        )
        
        self.assertFalse(success)
        self.assertIn('Failed to send email', message)

    def test_email_content_includes_invoice_details(self):
        """Test email content includes proper invoice details"""
        from billing.services.email_service import InvoiceEmailService
        
        with patch('billing.services.email_service.EmailMessage') as mock_email:
            mock_email_instance = MagicMock()
            mock_email.return_value = mock_email_instance
            
            pdf_content = b'fake pdf content'
            
            InvoiceEmailService.send_invoice_email(self.invoice, pdf_content)
            
            # Get the email body
            call_args = mock_email.call_args
            body = call_args[1]['body']
            
            # Check body contains invoice details
            self.assertIn(str(self.invoice.id), body)
            self.assertIn(self.teacher.get_full_name(), body)
            self.assertIn(self.teacher.email, body)
            self.assertIn('$75.00', body)
            self.assertIn('1', body)  # Number of lessons


class InvoiceServiceTests(TestCase):
    """Unit tests for invoice orchestration service"""
    
    def setUp(self):
        """Set up test data for invoice service tests"""
        self.teacher = User.objects.create_user(
            email='teacher@test.com',
            password='testpass123',
            first_name='John',
            last_name='Teacher',
            user_type='teacher',
            hourly_rate=75.00,
            is_approved=True
        )
        
        self.student = User.objects.create_user(
            email='student@test.com',
            password='testpass123',
            first_name='Alice',
            last_name='Johnson',
            user_type='student',
            is_approved=True
        )
        
        # Create lesson and invoice
        self.lesson = Lesson.objects.create(
            teacher=self.teacher,
            student=self.student,
            scheduled_date=timezone.now(),
            duration=1.0,
            rate=75.00,
            status='completed'
        )
        
        self.invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=self.teacher,
            status='pending',
            created_by=self.teacher,
            payment_balance=75.00
        )
        
        self.invoice.lessons.set([self.lesson])

    @patch('billing.services.invoice_service.InvoiceEmailService.send_invoice_email')
    @patch('billing.services.invoice_service.InvoicePDFGenerator.generate_pdf')
    def test_generate_and_send_invoice_success(self, mock_pdf_generator, mock_email_service):
        """Test successful invoice processing"""
        from billing.services.invoice_service import InvoiceProcessor
        
        # Mock successful PDF generation
        mock_pdf_generator.return_value = (True, b'fake pdf content')
        
        # Mock successful email sending
        mock_email_service.return_value = (True, 'Email sent successfully')
        
        success, message, pdf_content = InvoiceProcessor.generate_and_send_invoice(self.invoice)
        
        self.assertTrue(success)
        self.assertIn('successfully', message)
        self.assertEqual(pdf_content, b'fake pdf content')
        
        # Verify services were called
        mock_pdf_generator.assert_called_once()
        mock_email_service.assert_called_once_with(self.invoice, b'fake pdf content', None)

    @patch('billing.services.invoice_service.InvoicePDFGenerator.generate_pdf')
    def test_generate_and_send_invoice_pdf_failure(self, mock_pdf_generator):
        """Test invoice processing when PDF generation fails"""
        from billing.services.invoice_service import InvoiceProcessor
        
        # Mock PDF generation failure
        mock_pdf_generator.return_value = (False, None)
        
        success, message, pdf_content = InvoiceProcessor.generate_and_send_invoice(self.invoice)
        
        self.assertFalse(success)
        self.assertIn('Failed to generate PDF', message)
        self.assertIsNone(pdf_content)

    @patch('billing.services.invoice_service.InvoiceEmailService.send_invoice_email')
    @patch('billing.services.invoice_service.InvoicePDFGenerator.generate_pdf')
    def test_generate_and_send_invoice_email_failure(self, mock_pdf_generator, mock_email_service):
        """Test invoice processing when email sending fails"""
        from billing.services.invoice_service import InvoiceProcessor
        
        # Mock successful PDF generation
        mock_pdf_generator.return_value = (True, b'fake pdf content')
        
        # Mock email sending failure
        mock_email_service.return_value = (False, 'SMTP Error')
        
        success, message, pdf_content = InvoiceProcessor.generate_and_send_invoice(self.invoice)
        
        self.assertFalse(success)
        self.assertIn('email failed', message)
        self.assertEqual(pdf_content, b'fake pdf content')

    @patch('billing.services.invoice_service.InvoicePDFGenerator')
    def test_generate_and_send_invoice_exception_handling(self, mock_pdf_generator_class):
        """Test invoice processing exception handling"""
        from billing.services.invoice_service import InvoiceProcessor
        
        # Mock PDF generator to raise exception
        mock_pdf_generator_class.side_effect = Exception("Unexpected error")
        
        success, message, pdf_content = InvoiceProcessor.generate_and_send_invoice(self.invoice)
        
        self.assertFalse(success)
        self.assertIn('Processing failed', message)
        self.assertIsNone(pdf_content)

    @patch('billing.services.invoice_service.InvoiceEmailService.send_invoice_email')
    @patch('billing.services.invoice_service.InvoicePDFGenerator.generate_pdf')
    def test_generate_and_send_invoice_with_custom_recipient(self, mock_pdf_generator, mock_email_service):
        """Test invoice processing with custom recipient"""
        from billing.services.invoice_service import InvoiceProcessor
        
        # Mock successful PDF generation
        mock_pdf_generator.return_value = (True, b'fake pdf content')
        
        # Mock successful email sending
        mock_email_service.return_value = (True, 'Email sent successfully')
        
        custom_recipient = 'custom@test.com'
        success, message, pdf_content = InvoiceProcessor.generate_and_send_invoice(
            self.invoice, custom_recipient
        )
        
        self.assertTrue(success)
        
        # Verify email service was called with custom recipient
        mock_email_service.assert_called_once_with(self.invoice, b'fake pdf content', custom_recipient)


class PDFEmailIntegrationTests(APITestCase):
    """Integration tests for PDF generation and email sending in invoice creation"""
    
    def setUp(self):
        """Set up test data for integration tests"""
        self.teacher = User.objects.create_user(
            email='teacher@test.com',
            password='testpass123',
            first_name='John',
            last_name='Teacher',
            user_type='teacher',
            hourly_rate=75.00,
            is_approved=True
        )
        
        # Get auth token
        self.teacher_token = self._get_auth_token('teacher@test.com', 'testpass123')

    def _get_auth_token(self, email, password):
        """Helper method to get auth token"""
        response = self.client.post('/api/auth/token/', {
            'email': email,
            'password': password
        })
        if response.status_code == 200:
            return response.json()['access_token']
        return None

    @patch('billing.services.invoice_service.InvoiceProcessor.generate_and_send_invoice')
    def test_invoice_creation_triggers_pdf_generation(self, mock_invoice_processor):
        """Test that invoice creation triggers PDF generation and email sending"""
        # Mock successful PDF generation and email sending
        mock_invoice_processor.return_value = (True, 'Success', b'fake pdf content')
        
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify PDF generation was triggered
        mock_invoice_processor.assert_called_once()

    @patch('billing.services.invoice_service.InvoiceProcessor.generate_and_send_invoice')
    def test_invoice_creation_handles_pdf_generation_failure(self, mock_invoice_processor):
        """Test that invoice creation handles PDF generation failure gracefully"""
        # Mock PDF generation failure
        mock_invoice_processor.return_value = (False, 'PDF generation failed', None)
        
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        # Invoice creation should still succeed even if PDF generation fails
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify PDF generation was attempted
        mock_invoice_processor.assert_called_once()

    @patch('billing.services.invoice_service.InvoiceProcessor.generate_and_send_invoice')
    def test_invoice_creation_with_multiple_lessons_triggers_pdf(self, mock_invoice_processor):
        """Test PDF generation with multiple lessons"""
        # Mock successful PDF generation
        mock_invoice_processor.return_value = (True, 'Success', b'fake pdf content')
        
        data = {
            'lessons': [
                {
                    'student_name': 'Alice Johnson',
                    'duration': 1.0
                },
                {
                    'student_name': 'Bob Smith',
                    'duration': 1.5
                }
            ]
        }
        
        response = self.client.post(
            '/api/billing/invoices/teacher/submit-lessons/',
            data,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self.teacher_token}'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify PDF generation was triggered
        mock_invoice_processor.assert_called_once()
        
        # Verify the invoice has the correct number of lessons
        invoice_id = response.data['invoice']['id']
        from billing.models import Invoice
        invoice = Invoice.objects.get(id=invoice_id)
        self.assertEqual(invoice.lessons.count(), 2)
