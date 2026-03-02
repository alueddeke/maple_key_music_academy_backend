"""
Helcim CSV Generator Service

Generates CSV files in Helcim's required format for student billing.
Each row represents one student invoice.
"""

import csv
from io import StringIO
from datetime import datetime
from django.http import HttpResponse


def generate_helcim_csv(student_invoices, school_settings):
    """
    Generate Helcim CSV from StudentInvoice records.

    Args:
        student_invoices: QuerySet or list of StudentInvoice objects
        school_settings: SchoolSettings object for payment terms

    Returns:
        HttpResponse with CSV file for download
    """
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

    # Write data rows
    for invoice in student_invoices:
        # Format date: MM/DD/YYYY HH:MM
        date_issued = invoice.generated_at.strftime('%m/%d/%Y %H:%M')

        row = [
            # Order identification
            invoice.invoice_number,  # ORDER_NUMBER
            date_issued,  # DATE_ISSUED
            '',  # DATE_PAID (blank - not paid yet)
            'CAD',  # CURRENCY
            'DUE',  # STATUS
            school_settings.payment_terms,  # PAYMENT_TERMS

            # Customer
            invoice.student.id,  # CUSTOMER_CODE
            f'{invoice.amount:.2f}',  # AMOUNT

            # Discounts/Shipping/Tax
            '0.00',  # AMOUNT_DISCOUNT
            '0.00',  # AMOUNT_SHIPPING
            '0.00',  # AMOUNT_TAX (tax included in amount)

            # Additional details
            '',  # COMMENTS (optional)
            '',  # DISCOUNT_DETAILS
            '',  # TAX_DETAILS (blank since tax included)
            '',  # PURCHASE_ORDER_NUMBER

            # Billing address
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
        first_invoice = student_invoices[0] if hasattr(student_invoices, '__getitem__') else student_invoices.first()
        batch = first_invoice.batch
        filename = f'helcim_invoices_{batch.batch_number}.csv'
    else:
        filename = f'helcim_invoices_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response
