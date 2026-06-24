"""
Helcim CSV Generator Service

Generates CSV files in Helcim's required format for student billing.
Each row represents one lesson item within a student invoice (one row per BatchLessonItem with charge > 0).
"""

import csv
from decimal import Decimal
from io import StringIO
from datetime import datetime
from django.db.models import prefetch_related_objects
from django.http import HttpResponse


def generate_helcim_csv(student_invoices, school_settings):
    """
    Generate Helcim CSV from StudentInvoice records.

    Args:
        student_invoices: QuerySet or list of StudentInvoice objects
        school_settings: SchoolSettings object for payment terms

    Returns:
        HttpResponse with CSV file for download. The response contains one row per
        BatchLessonItem (with charge > 0) per invoice. All lesson rows for a given
        StudentInvoice share the same ORDER_NUMBER. Lessons where
        calculate_student_charge() returns Decimal('0.00') (trial + cancelled) are
        excluded.
    """
    # Prefetch lesson_items to avoid N+1 queries on invoice.lesson_items.all()
    # Uses prefetch_related_objects() (not QuerySet.prefetch_related) because
    # the caller passes a plain Python list, not a QuerySet.
    if student_invoices:
        prefetch_related_objects(student_invoices, 'lesson_items')

    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)

    # Write header row
    headers = [
        'ORDER_NUMBER', 'DATE_ISSUED', 'DATE_PAID', 'CURRENCY', 'STATUS', 'PAYMENT_TERMS',
        'CUSTOMER_CODE', 'AMOUNT', 'AMOUNT_DISCOUNT', 'AMOUNT_SHIPPING', 'AMOUNT_TAX',
        'COMMENTS', 'DISCOUNT_DETAILS', 'TAX_DETAILS', 'PURCHASE_ORDER_NUMBER',
        'BILLING_CONTACT_NAME', 'BILLING_BUSINESS_NAME', 'BILLING_STREET1', 'BILLING_STREET2',
        'BILLING_CITY', 'BILLING_PROVINCE', 'BILLING_COUNTRY', 'BILLING_POSTALCODE',
        'BILLING_PHONE', 'BILLING_FAX', 'BILLING_EMAIL',
        'SHIPPING_CONTACT_NAME', 'SHIPPING_BUSINESS_NAME', 'SHIPPING_STREET1', 'SHIPPING_STREET2',
        'SHIPPING_CITY', 'SHIPPING_PROVINCE', 'SHIPPING_COUNTRY', 'SHIPPING_POSTALCODE',
        'SHIPPING_PHONE', 'SHIPPING_FAX', 'SHIPPING_EMAIL'
    ]
    writer.writerow(headers)

    # Write data rows — one row per BatchLessonItem (charge > 0) per invoice
    for invoice in student_invoices:
        # Format date once per invoice (shared across all lesson rows)
        date_issued = invoice.generated_at.strftime('%m/%d/%Y %H:%M')

        for item in invoice.lesson_items.all():
            # Compute charge once — avoids double-call if method signature ever changes
            charge = item.calculate_student_charge()

            # Skip zero-charge lessons (trial and cancelled)
            if charge == Decimal('0.00'):
                continue

            # COMMENTS: lesson date formatted as 'Jan 15, 2026' (%-d strips leading zero on Linux)
            comments = item.scheduled_date.strftime('%b %-d, %Y')

            # AMOUNT: per-lesson charge formatted to 2 decimal places
            amount = f'{charge:.2f}'

            row = [
                # Order identification
                invoice.invoice_number,  # ORDER_NUMBER — shared across all lessons for this invoice
                date_issued,  # DATE_ISSUED
                '',  # DATE_PAID (blank - not paid yet)
                'CAD',  # CURRENCY
                'DUE',  # STATUS
                school_settings.payment_terms,  # PAYMENT_TERMS

                # Customer
                invoice.student.id,  # CUSTOMER_CODE
                amount,  # AMOUNT — per-lesson charge

                # Discounts/Shipping/Tax
                '0.00',  # AMOUNT_DISCOUNT
                '0.00',  # AMOUNT_SHIPPING
                '0.00',  # AMOUNT_TAX (tax included in amount)

                # Additional details
                comments,  # COMMENTS — lesson date (e.g. 'Jan 15, 2026')
                '',  # DISCOUNT_DETAILS
                '',  # TAX_DETAILS (blank since tax included)
                '',  # PURCHASE_ORDER_NUMBER

                # Billing address — copied from StudentInvoice to every lesson row
                invoice.billing_contact_name,  # BILLING_CONTACT_NAME
                '',  # BILLING_BUSINESS_NAME (blank for individual students)
                invoice.billing_street_address,  # BILLING_STREET1
                '',  # BILLING_STREET2 (not used)
                invoice.billing_city,  # BILLING_CITY
                invoice.billing_province,  # BILLING_PROVINCE
                'Canada',  # BILLING_COUNTRY
                invoice.billing_postal_code,  # BILLING_POSTALCODE
                invoice.billing_phone,  # BILLING_PHONE
                '',  # BILLING_FAX (not used)
                invoice.billing_email,  # BILLING_EMAIL

                # Shipping address (all blank for digital services)
                '', '', '', '', '', '', '', '', '', '', ''
            ]
            writer.writerow(row)

    # Create HTTP response
    output.seek(0)
    response = HttpResponse(output.getvalue(), content_type='text/csv')

    # Generate filename with batch info (if available)
    if student_invoices:
        batch = student_invoices[0].batch
        filename = f'helcim_invoices_{batch.batch_number}.csv'
    else:
        filename = f'helcim_invoices_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response
