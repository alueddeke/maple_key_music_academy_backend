import io
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT
from django.conf import settings
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class InvoicePDFGenerator:
    def __init__(self, invoice):
        self.invoice = invoice
        self.buffer = io.BytesIO()

    def generate_pdf(self):
        """Generate PDF and return success status and PDF content"""
        try:
            # Wave invoice red color
            wave_red = colors.HexColor('#E31E24')

            # Create PDF document with smaller margins
            doc = SimpleDocTemplate(
                self.buffer,
                pagesize=A4,
                rightMargin=36,
                leftMargin=36,
                topMargin=36,
                bottomMargin=36
            )

            # Build PDF content
            story = []
            styles = getSampleStyleSheet()

            # Create custom styles - Using Helvetica-Bold (ReportLab standard)
            invoice_title_style = ParagraphStyle(
                'InvoiceTitle',
                parent=styles['Normal'],
                fontSize=36,
                fontName='Helvetica-Bold',
                textColor=colors.black,
                alignment=TA_RIGHT,
                spaceAfter=15,  # Add bottom margin
                leading=36  # Set line height to match font size
            )

            school_brand_style = ParagraphStyle(
                'SchoolBrand',
                parent=styles['Normal'],
                fontSize=14,
                fontName='Helvetica-Bold',
                textColor=colors.black,  # Changed from red to black
                alignment=TA_RIGHT,
                spaceAfter=5,  # Add small bottom margin
                leading=14  # Set line height to match font size
            )

            country_style = ParagraphStyle(
                'Country',
                parent=styles['Normal'],
                fontSize=10,
                fontName='Helvetica',
                alignment=TA_RIGHT,
                spaceAfter=20,
                leading=10  # Set line height to match font size
            )

            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Normal'],
                fontSize=10,
                fontName='Helvetica-Bold',
                spaceAfter=6,
                textColor=colors.grey
            )

            bold_style = ParagraphStyle(
                'BoldStyle',
                parent=styles['Normal'],
                fontSize=10,
                fontName='Helvetica-Bold'
            )

            normal_style = ParagraphStyle(
                'NormalWrapped',
                parent=styles['Normal'],
                fontSize=10,
                fontName='Helvetica',
                wordWrap='CJK'
            )

            # Header section with TEACHER INVOICE title and school branding
            # Use table structure to match billing section alignment
            header_table_data = [
                ['', '', '', 'TEACHER INVOICE'],
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
                ('BOTTOMPADDING', (3, 0), (3, 0), 45),  # Add bottom margin to INVOICE

                ('FONTSIZE', (3, 1), (3, 1), 14),
                ('FONTNAME', (3, 1), (3, 1), 'Helvetica-Bold'),
                ('TEXTCOLOR', (3, 1), (3, 1), colors.black),
                ('ALIGN', (3, 1), (3, 1), 'RIGHT'),
                ('VALIGN', (3, 1), (3, 1), 'TOP'),
                ('BOTTOMPADDING', (3, 1), (3, 1), 5),  # Add small bottom margin

                ('FONTSIZE', (3, 2), (3, 2), 10),
                ('TEXTCOLOR', (3, 2), (3, 2), colors.black),
                ('ALIGN', (3, 2), (3, 2), 'RIGHT'),
                ('VALIGN', (3, 2), (3, 2), 'TOP'),

                # Remove all borders and spacing for other cells
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))

            story.append(header_table)

            # Add divider line under header
            divider_table_data = [['']]
            divider_table = Table(divider_table_data, colWidths=[8.1*inch])
            divider_table.setStyle(TableStyle([
                ('LINEBELOW', (0, 0), (0, 0), 1, colors.lightgrey),  # Single line in very light grey
                ('TOPPADDING', (0, 0), (0, 0), 10),
                ('BOTTOMPADDING', (0, 0), (0, 0), 10),
            ]))
            story.append(divider_table)
            story.append(Spacer(1, 20))

            # Create two-column layout for Teacher Info and Invoice Details
            left_column = []
            right_column = []

            # Left column - Teacher Information
            left_column.append(Paragraph("TEACHER INFORMATION", heading_style))
            teacher = self.invoice.teacher
            left_column.append(Paragraph(f"<b>{teacher.get_full_name()}</b>", normal_style))
            left_column.append(Paragraph(f"{teacher.email}", normal_style))
            if teacher.phone_number:
                left_column.append(Paragraph(f"{teacher.phone_number}", normal_style))
            if teacher.address:
                address_lines = teacher.address.replace(',', '<br/>').replace('\n', '<br/>')
                left_column.append(Paragraph(address_lines, normal_style))

            # Right column - Invoice Details (right-aligned)
            right_align_style = ParagraphStyle('RightAlign', parent=normal_style, alignment=TA_RIGHT)
            right_align_bold = ParagraphStyle('RightAlignBold', parent=bold_style, alignment=TA_RIGHT)

            right_column.append(Paragraph(f"<b>Invoice Number:</b> {self.invoice.id}", right_align_style))
            right_column.append(Paragraph(f"<b>Invoice Date:</b> {self.invoice.created_at.strftime('%B %d, %Y')}", right_align_style))
            right_column.append(Paragraph(f"<b>Total Amount (CAD):</b> ${self.invoice.payment_balance:.2f}", right_align_bold))

            # Combine columns into a table - Aligned with main table width
            info_table_data = []
            max_rows = max(len(left_column), len(right_column))
            for i in range(max_rows):
                left_cell = left_column[i] if i < len(left_column) else Paragraph("", normal_style)
                right_cell = right_column[i] if i < len(right_column) else Paragraph("", normal_style)
                info_table_data.append([left_cell, right_cell])

            # Use same total width as main table (4.5 + 1.2 + 1.2 + 1.2 = 8.1 inches)
            info_table = Table(info_table_data, colWidths=[4.5*inch, 3.6*inch])
            info_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ]))

            story.append(info_table)
            story.append(Spacer(1, 25))

            # Lessons breakdown table
            if self.invoice.lessons.exists():
                # Table data
                data = [['Student Name', 'Date', 'Duration (hrs)', 'Total ($)']]

                for lesson in self.invoice.lessons.all():
                    # Format the scheduled date
                    lesson_date = lesson.scheduled_date.strftime('%Y-%m-%d') if lesson.scheduled_date else 'N/A'

                    data.append([
                        Paragraph(lesson.student.get_full_name(), normal_style),
                        lesson_date,
                        f"{lesson.duration:.1f}",
                        f"${lesson.total_cost():.2f}"
                    ])

                # Create table with wrapping enabled (NO totals inside) - Full width, no borders
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

                story.append(table)
                story.append(Spacer(1, 15))

                # Totals section - OUTSIDE the table (like Wave example) - Aligned with table
                totals_table_data = [
                    ['', '', 'TOTAL:', f"${self.invoice.payment_balance:.2f}"]
                ]

                totals_table = Table(totals_table_data, colWidths=[4.5*inch, 1.2*inch, 1.2*inch, 1.2*inch])
                totals_table.setStyle(TableStyle([
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('FONTNAME', (2, 0), (-1, -1), 'Helvetica-Bold'),
                    ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                    ('ALIGN', (3, 0), (3, -1), 'CENTER'),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ]))

                story.append(totals_table)
            else:
                story.append(Paragraph("No lessons found for this invoice.", normal_style))

            # Add some spacing at the end
            story.append(Spacer(1, 25))

            # Add footer/notes - Aligned with table width
            notes_table_data = [
                [Paragraph("Notes / Terms", heading_style), ''],
                [Paragraph("Thank you for your service!", normal_style), '']
            ]

            notes_table = Table(notes_table_data, colWidths=[4.5*inch, 3.6*inch])
            notes_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ]))

            story.append(notes_table)

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
