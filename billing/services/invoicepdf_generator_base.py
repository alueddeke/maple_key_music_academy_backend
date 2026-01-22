import io
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT
from django.conf import settings
from abc import ABC, abstractmethod
import logging
from datetime import datetime
from .pdf_styles import get_invoice_styles

logger = logging.getLogger(__name__)

class BaseInvoicePDFGenerator(ABC):
    """Abstract base class for invoice PDF generation"""

    def __init__(self, invoice):
        self.invoice = invoice
        self.buffer = io.BytesIO()

    def generate_pdf(self):
        """Generate PDF and return success status and PDF content"""
        try:
            # Wave invoice red color
            wave_red = colors.HexColor('#E31E24')

            # Create PDF document
            doc = self._create_document()

            # Build PDF content
            story = []

            # Get shared invoice styles
            pdf_styles = get_invoice_styles()

            # Build sections using helper methods
            story.append(self._create_header(pdf_styles))
            story.append(self._create_divider())
            story.append(Spacer(1, 20))
            story.append(self._create_recipient_section(pdf_styles))
            story.append(Spacer(1, 25))

            lessons_table = self._create_lessons_table(pdf_styles, wave_red)
            if lessons_table:
                story.append(lessons_table)
                story.append(Spacer(1, 15))
                story.append(self._create_totals_section())
            else:
                story.append(Paragraph("No lessons found for this invoice.", pdf_styles['normal_style']))

            story.append(Spacer(1, 25))
            story.append(self._create_notes_section(pdf_styles))

            # Build PDF
            doc.build(story)

            # Get PDF content
            pdf_content = self.buffer.getvalue()
            self.buffer.close()

            logger.info(f"Successfully generated PDF for invoice {self.invoice.id}")
            return True, pdf_content

        except Exception as e:
            logger.error(f"Failed to generate PDF for invoice {self.invoice.id}: {str(e)}")
            self.buffer.close()
            return False, None

    # Abstract methods that subclasses MUST implement, "these fields are required" to make invoice pdf
    @abstractmethod
    def get_invoice_title(self):
        """Return the invoice title text (e.g., 'INVOICE' or 'TEACHER INVOICE')"""
        pass

    @abstractmethod
    def get_left_column_heading(self):
        """Return left column heading text (e.g., 'BILL TO' or 'TEACHER INFORMATION')"""
        pass

    @abstractmethod
    def get_left_column_content(self, pdf_styles):
        """Return list of Paragraph objects for left column recipient info"""
        pass

    @abstractmethod
    def get_right_column_content(self, pdf_styles):
        """Return list of Paragraph objects for right column invoice details"""
        pass

    @abstractmethod
    def get_lessons_table_header(self):
        """Return list of column headers (e.g., ['Student Name', 'Date', ...])"""
        pass

    @abstractmethod
    def get_lessons_data(self):
        """Return queryset/list of lessons to include in table"""
        pass

    @abstractmethod
    def format_lesson_row(self, lesson, pdf_styles):
        """Return list representing one lesson row data"""
        pass

    @abstractmethod
    def get_total_amount(self):
        """Return total amount for this invoice"""
        pass

    @abstractmethod
    def get_totals_table_rows(self):
        """Return list of rows for totals table"""
        pass

    @abstractmethod
    def get_notes_text(self):
        """Return notes/terms text for footer"""
        pass

    # Concrete helper methods using abstract methods
    def _create_document(self):
        """Create PDF document with standard settings"""
        return SimpleDocTemplate(
            self.buffer,
            pagesize=A4,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

    def _create_header(self, pdf_styles):
        """Create header with title and school branding"""
        header_table_data = [
            ['', '', '', self.get_invoice_title()],  # Uses abstract method
            ['', '', '', 'Maple Key Music Academy'],
            ['', '', '', 'Canada']
        ]

        header_table = Table(header_table_data, colWidths=[4.5*inch, 1.2*inch, 1.2*inch, 1.2*inch])
        header_table.setStyle(TableStyle([
            ('FONTSIZE', (3, 0), (3, 0), 36),
            ('FONTNAME', (3, 0), (3, 0), 'Helvetica-Bold'),
            ('TEXTCOLOR', (3, 0), (3, 0), colors.black),
            ('ALIGN', (3, 0), (3, 0), 'RIGHT'),
            ('VALIGN', (3, 0), (3, 0), 'TOP'),
            ('BOTTOMPADDING', (3, 0), (3, 0), 45),

            ('FONTSIZE', (3, 1), (3, 1), 14),
            ('FONTNAME', (3, 1), (3, 1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (3, 1), (3, 1), colors.black),
            ('ALIGN', (3, 1), (3, 1), 'RIGHT'),
            ('VALIGN', (3, 1), (3, 1), 'TOP'),
            ('BOTTOMPADDING', (3, 1), (3, 1), 5),

            ('FONTSIZE', (3, 2), (3, 2), 10),
            ('TEXTCOLOR', (3, 2), (3, 2), colors.black),
            ('ALIGN', (3, 2), (3, 2), 'RIGHT'),
            ('VALIGN', (3, 2), (3, 2), 'TOP'),

            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))

        return header_table

    def _create_divider(self):
        """Create horizontal divider line"""
        divider_table_data = [['']]
        divider_table = Table(divider_table_data, colWidths=[8.1*inch])
        divider_table.setStyle(TableStyle([
            ('LINEBELOW', (0, 0), (0, 0), 1, colors.lightgrey),
            ('TOPPADDING', (0, 0), (0, 0), 10),
            ('BOTTOMPADDING', (0, 0), (0, 0), 10),
        ]))
        return divider_table

    def _create_recipient_section(self, pdf_styles):
        """Create two-column recipient/details section"""
        # Get content from subclass
        left_column = self.get_left_column_content(pdf_styles)
        right_column = self.get_right_column_content(pdf_styles)

        # Combine columns into table
        info_table_data = []
        max_rows = max(len(left_column), len(right_column))
        for i in range(max_rows):
            left_cell = left_column[i] if i < len(left_column) else Paragraph("", pdf_styles['normal_style'])
            right_cell = right_column[i] if i < len(right_column) else Paragraph("", pdf_styles['normal_style'])
            info_table_data.append([left_cell, right_cell])

        info_table = Table(info_table_data, colWidths=[4.5*inch, 3.6*inch])
        info_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ]))

        return info_table

    def _create_lessons_table(self, pdf_styles, wave_red):
        """Create lessons breakdown table"""
        lessons_data = self.get_lessons_data()

        if not lessons_data:
            return None

        # Table header from subclass
        header = self.get_lessons_table_header()
        data = [header]

        # Table rows from subclass
        for lesson in lessons_data:
            row = self.format_lesson_row(lesson, pdf_styles)
            data.append(row)

        # Create table with shared styling
        table = Table(data, colWidths=[4.5*inch, 1.2*inch, 1.2*inch, 1.2*inch])
        table.setStyle(TableStyle([
            # Header row styling - RED theme
            ('BACKGROUND', (0, 0), (-1, 0), wave_red),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),

            # Data rows styling
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),

            # Add grey border bottom to each data row
            ('LINEBELOW', (0, 1), (-1, -1), 1, colors.grey),

            # Add very light grey border around entire table
            ('BOX', (0, 0), (-1, -1), 1, colors.lightgrey),
        ]))

        return table

    def _create_totals_section(self):
        """Create totals section"""
        totals_table_data = self.get_totals_table_rows()

        totals_table = Table(totals_table_data, colWidths=[4.5*inch, 1.2*inch, 1.2*inch, 1.2*inch])
        totals_table.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('FONTNAME', (2, 0), (-1, -1), 'Helvetica-Bold'),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('ALIGN', (3, 0), (3, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))

        return totals_table

    def _create_notes_section(self, pdf_styles):
        """Create notes/terms section"""
        notes_text = self.get_notes_text()

        notes_table_data = [
            [Paragraph("Notes / Terms", pdf_styles['heading_style']), ''],
            [Paragraph(notes_text, pdf_styles['normal_style']), '']
        ]

        notes_table = Table(notes_table_data, colWidths=[4.5*inch, 3.6*inch])
        notes_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ]))

        return notes_table
