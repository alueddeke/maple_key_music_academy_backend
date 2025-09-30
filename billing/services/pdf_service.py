import io
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
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
            # Create PDF document
            doc = SimpleDocTemplate(
                self.buffer,
                pagesize=A4,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )
            
            # Build PDF content
            story = []
            styles = getSampleStyleSheet()
            
            # Create custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Title'],
                fontSize=18,
                spaceAfter=30,
                alignment=1  # Center alignment
            )
            
            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Heading2'],
                fontSize=14,
                spaceAfter=12,
                textColor=colors.darkblue
            )
            
            # Title
            story.append(Paragraph("TEACHER INVOICE", title_style))
            story.append(Spacer(1, 20))
            
            # Invoice details
            story.append(Paragraph(f"Invoice #{self.invoice.id}", heading_style))
            story.append(Paragraph(f"Date: {self.invoice.created_at.strftime('%B %d, %Y')}", styles['Normal']))
            story.append(Spacer(1, 20))
            
            # Teacher information
            story.append(Paragraph("Teacher Information:", heading_style))
            teacher = self.invoice.teacher
            story.append(Paragraph(f"Name: {teacher.get_full_name()}", styles['Normal']))
            story.append(Paragraph(f"Email: {teacher.email}", styles['Normal']))
            if teacher.phone_number:
                story.append(Paragraph(f"Phone: {teacher.phone_number}", styles['Normal']))
            if teacher.address:
                story.append(Paragraph(f"Address: {teacher.address}", styles['Normal']))
            story.append(Spacer(1, 20))
            
            # Lessons breakdown
            story.append(Paragraph("Lessons Breakdown:", heading_style))
            
            if self.invoice.lessons.exists():
                # Table data
                data = [['Student Name', 'Date', 'Duration (hrs)', 'Rate ($)', 'Total ($)']]
                
                for lesson in self.invoice.lessons.all():
                    # Format the scheduled date
                    lesson_date = lesson.scheduled_date.strftime('%Y-%m-%d') if lesson.scheduled_date else 'N/A'
                    
                    data.append([
                        lesson.student.get_full_name(),
                        lesson_date,
                        f"{lesson.duration:.1f}",
                        f"${lesson.rate:.2f}",
                        f"${lesson.total_cost():.2f}"
                    ])
                
                # Add total row
                data.append(['', '', '', 'TOTAL:', f"${self.invoice.payment_balance:.2f}"])
                
                # Create table
                table = Table(data, colWidths=[2*inch, 1.2*inch, 1*inch, 1*inch, 1*inch])
                table.setStyle(TableStyle([
                    # Header row styling
                    ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 12),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    
                    # Data rows styling
                    ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
                    ('FONTSIZE', (0, 1), (-1, -2), 10),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.lightgrey]),
                    
                    # Total row styling
                    ('BACKGROUND', (0, -1), (-1, -1), colors.lightblue),
                    ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, -1), (-1, -1), 12),
                    
                    # Grid
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                
                story.append(table)
            else:
                story.append(Paragraph("No lessons found for this invoice.", styles['Normal']))
            
            # Add some spacing at the end
            story.append(Spacer(1, 30))
            
            # Add footer
            story.append(Paragraph("Thank you for your service!", styles['Normal']))
            
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
