"""
Shared PDF styles for invoice generation.

This module provides common styles used across all invoice types
(teacher payment invoices and student billing invoices).
"""

from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib import colors


def get_invoice_styles():
    """
    Get standard invoice paragraph styles.

    Returns:
        dict: Dictionary of ParagraphStyle objects with keys:
            - invoice_title_style: Large bold title for invoice type
            - school_brand_style: School name branding
            - country_style: Location text
            - heading_style: Section headings
            - bold_style: Bold text
            - normal_style: Normal wrapped text
    """
    styles = getSampleStyleSheet()

    return {
        'invoice_title_style': ParagraphStyle(
            'InvoiceTitle',
            parent=styles['Normal'],
            fontSize=36,
            fontName='Helvetica-Bold',
            textColor=colors.black,
            alignment=TA_RIGHT,
            spaceAfter=15,
            leading=36
        ),

        'school_brand_style': ParagraphStyle(
            'SchoolBrand',
            parent=styles['Normal'],
            fontSize=14,
            fontName='Helvetica-Bold',
            textColor=colors.black,
            alignment=TA_RIGHT,
            spaceAfter=5,
            leading=14
        ),

        'country_style': ParagraphStyle(
            'Country',
            parent=styles['Normal'],
            fontSize=10,
            fontName='Helvetica',
            alignment=TA_RIGHT,
            spaceAfter=20,
            leading=10
        ),

        'heading_style': ParagraphStyle(
            'CustomHeading',
            parent=styles['Normal'],
            fontSize=10,
            fontName='Helvetica-Bold',
            spaceAfter=6,
            textColor=colors.grey
        ),

        'bold_style': ParagraphStyle(
            'BoldStyle',
            parent=styles['Normal'],
            fontSize=10,
            fontName='Helvetica-Bold'
        ),

        'normal_style': ParagraphStyle(
            'NormalWrapped',
            parent=styles['Normal'],
            fontSize=10,
            fontName='Helvetica',
            wordWrap='CJK'
        )
    }
