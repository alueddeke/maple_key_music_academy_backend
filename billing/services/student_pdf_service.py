import io
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from django.conf import settings
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class StudentInvoicePDFGenerator:
    def __init__(self, invoice, student_lessons):
        self.invoice = invoice
        self.student_lessons = student_lessons  # Lessons for this specific student
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
            
            bold_style = ParagraphStyle(
                'BoldStyle',
                parent=styles['Normal'],
                fontSize=12,
                fontName='Helvetica-Bold'
            )
            
            # Calculate due date (14 days from generation)
            due_date = datetime.now() + timedelta(days=14)
            
            # Calculate total amount for this student
            student_total = sum(lesson.total_cost() for lesson in self.student_lessons)
            
            # Get student info
            student = self.student_lessons[0].student if self.student_lessons else None
            
            # Header with school branding
            story.append(Paragraph("Maple Key Music Academy", ParagraphStyle(
                'SchoolBrand',
                parent=styles['Normal'],
                fontSize=16,
                fontName='Helvetica-Bold',
                textColor=colors.darkblue,
                alignment=2  # Right alignment
            )))
            story.append(Spacer(1, 20))
            
            # Title
            story.append(Paragraph("STUDENT INVOICE", title_style))
            story.append(Spacer(1, 20))
            
            # Bill To section
            story.append(Paragraph("BILL TO", heading_style))
            if student:
                story.append(Paragraph(f"{student.get_full_name()}", styles['Normal']))
                if student.address:
                    story.append(Paragraph(f"{student.address}", styles['Normal']))
                if student.phone_number:
                    story.append(Paragraph(f"{student.phone_number}", styles['Normal']))
                if student.email:
                    story.append(Paragraph(f"{student.email}", styles['Normal']))
            story.append(Spacer(1, 20))
            
            # Invoice details
            story.append(Paragraph(f"Invoice Number: {self.invoice.id}", styles['Normal']))
            story.append(Paragraph(f"Invoice Date: {datetime.now().strftime('%B %d, %Y')}", styles['Normal']))
            story.append(Paragraph(f"Payment Due: {due_date.strftime('%B %d, %Y')}", bold_style))
            story.append(Paragraph(f"Amount Due (CAD): ${student_total:.2f}", bold_style))
            story.append(Spacer(1, 20))
            
            # Items table
            story.append(Paragraph("Items", heading_style))
            
            # Table data
            data = [['Items', 'Quantity', 'Price', 'Amount']]
            
            # Group lessons by instrument/type
            lesson_groups = {}
            for lesson in self.student_lessons:
                # Create a key for grouping (you can customize this logic)
                key = f"Music Lessons"
                if key not in lesson_groups:
                    lesson_groups[key] = {
                        'quantity': 0,
                        'total_hours': 0,
                        'rate': lesson.rate,
                        'description': f"Music Lessons<br/>{lesson.teacher.get_full_name()}, {lesson.duration:.1f} hour lessons"
                    }
                lesson_groups[key]['quantity'] += 1
                lesson_groups[key]['total_hours'] += lesson.duration
            
            # Add grouped lessons to table
            for group_name, group_data in lesson_groups.items():
                data.append([
                    group_data['description'],
                    f"{group_data['quantity']}",
                    f"${group_data['rate']:.2f}",
                    f"${group_data['total_hours'] * group_data['rate']:.2f}"
                ])
            
            # Add total row
            data.append(['', '', 'Total:', f"${student_total:.2f}"])
            data.append(['', '', 'Amount Due (CAD):', f"${student_total:.2f}"])
            
            # Create table
            table = Table(data, colWidths=[3*inch, 1*inch, 1*inch, 1*inch])
            table.setStyle(TableStyle([
                # Header row styling
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                
                # Data rows styling
                ('BACKGROUND', (0, 1), (-1, -3), colors.beige),
                ('FONTSIZE', (0, 1), (-1, -3), 10),
                ('ROWBACKGROUNDS', (0, 1), (-1, -3), [colors.white, colors.lightgrey]),
                
                # Total rows styling
                ('BACKGROUND', (0, -2), (-1, -1), colors.lightblue),
                ('FONTNAME', (0, -2), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, -2), (-1, -1), 12),
                
                # Grid
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(table)
            story.append(Spacer(1, 20))
            
            # Notes section
            story.append(Paragraph("Notes / Terms", heading_style))
            story.append(Paragraph("E-Transfer - maplekeymusic.academy@gmail.com", styles['Normal']))
            
            # Build PDF
            doc.build(story)
            
            # Get PDF content
            pdf_content = self.buffer.getvalue()
            self.buffer.close()
            
            logger.info(f"Successfully generated student invoice PDF for invoice {self.invoice.id}")
            return True, pdf_content
            
        except Exception as e:
            logger.error(f"Failed to generate student invoice PDF for invoice {self.invoice.id}: {str(e)}")
            self.buffer.close()
            return False, None
