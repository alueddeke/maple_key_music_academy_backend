from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.utils import timezone
from ..models import Invoice, Lesson, BillableContact, MonthlyInvoiceBatch, BatchLessonItem, StudentInvoice, GlobalRateSettings
from ..serializers import (
    UserSerializer, LessonSerializer, InvoiceSerializer, DetailedInvoiceSerializer,
    MonthlyInvoiceBatchSerializer, BatchLessonItemSerializer
)
from custom_auth.decorators import (
    teacher_required, management_required, teacher_or_management_required
)
import logging
import uuid

logger = logging.getLogger(__name__)
User = get_user_model()


# INVOICE MANAGEMENT

@api_view(['GET', 'POST'])
@teacher_or_management_required
def teacher_invoice_list(request):
    """Teacher payment invoices"""
    if request.method == 'GET':
        if request.user.user_type == 'management':
            invoices = Invoice.objects.filter(
                invoice_type='teacher_payment',
                school=request.user.school
            ).order_by('-created_at')
        else:  # teacher
            invoices = Invoice.objects.filter(
                invoice_type='teacher_payment',
                teacher=request.user,
                school=request.user.school
            ).order_by('-created_at')

        # Use DetailedInvoiceSerializer to include lesson details
        serializer = DetailedInvoiceSerializer(invoices, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        # Create teacher payment invoice
        data = request.data.copy()
        data['invoice_type'] = 'teacher_payment'

        if request.user.user_type == 'teacher':
            data['teacher'] = request.user.id
            data['created_by'] = request.user.id

        serializer = InvoiceSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@teacher_required
def teacher_invoice_stats(request):
    """Get teacher's invoice statistics including rejected count"""
    teacher = request.user

    # Get counts by status (school filtering implicit via teacher FK)
    pending_count = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        school=teacher.school,
        status='pending'
    ).count()

    rejected_count = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        school=teacher.school,
        status='rejected'
    ).count()

    approved_count = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        school=teacher.school,
        status='approved'
    ).count()

    paid_count = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        school=teacher.school,
        status='paid'
    ).count()

    # Get most recent rejected invoices
    recent_rejected = Invoice.objects.filter(
        invoice_type='teacher_payment',
        teacher=teacher,
        school=teacher.school,
        status='rejected'
    ).order_by('-rejected_at')[:5]

    rejected_invoices = []
    for invoice in recent_rejected:
        rejected_invoices.append({
            'id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'total_amount': str(invoice.total_amount),
            'rejected_at': invoice.rejected_at,
            'rejected_by_name': invoice.rejected_by.get_full_name() if invoice.rejected_by else None,
            'rejection_reason': invoice.rejection_reason,
        })

    return Response({
        'pending_count': pending_count,
        'rejected_count': rejected_count,
        'approved_count': approved_count,
        'paid_count': paid_count,
        'recent_rejected': rejected_invoices,
    })

@api_view(['POST'])
@teacher_required
def submit_lessons_for_invoice(request):
    """
    Teacher submits lesson details and creates invoice in one transaction.

    Expected request body:
    {
        "month": "January 2024",
        "lessons": [
            {
                "student_name": "John Smith",
                "student_email": "john@example.com",  # Optional, for student lookup
                "scheduled_date": "2024-01-15T14:00:00Z",
                "duration": 1.0,
                "rate": 80.00,  # Optional, defaults to teacher's hourly rate
                "teacher_notes": "Worked on scales and arpeggios"
            }
        ],
        "due_date": "2024-02-15T00:00:00Z"
    }
    """
    try:
        data = request.data.copy()
        lessons_data = data.get('lessons', [])

        if not lessons_data:
            return Response({'error': 'No lessons provided'}, status=status.HTTP_400_BAD_REQUEST)

        # VALIDATION: Check all students have complete billing information
        validation_errors = []
        for lesson_data in lessons_data:
            student_email = lesson_data.get('student_email')
            student_name = lesson_data.get('student_name', 'Unknown Student')

            # Generate email if not provided (same logic as creation)
            if not student_email:
                temp_email = f"noemail_{uuid.uuid4().hex[:12]}@maplekeymusic.internal"
                student_email = temp_email

            # Check if student exists
            try:
                student = User.objects.get(email=student_email, user_type='student')

                # Check for complete billing contact
                primary_contact = BillableContact.objects.filter(
                    student=student,
                    is_primary=True
                ).first()

                if not primary_contact:
                    validation_errors.append({
                        'student': student_name,
                        'email': student_email,
                        'error': 'No billing contact found. Please add complete billing information in Student Management.'
                    })
                else:
                    # Check all required fields
                    missing_fields = []
                    incomplete_fields = {}

                    # Handle both old 'state' and new 'province' field names for backward compatibility
                    province_value = getattr(primary_contact, 'province', None) or getattr(primary_contact, 'state', None)

                    required_fields = {
                        'first_name': primary_contact.first_name,
                        'last_name': primary_contact.last_name,
                        'email': primary_contact.email,
                        'phone': primary_contact.phone,
                        'street_address': primary_contact.street_address,
                        'city': primary_contact.city,
                        'province': province_value,
                        'postal_code': primary_contact.postal_code
                    }

                    for field_name, field_value in required_fields.items():
                        if not field_value or field_value.strip() == '':
                            missing_fields.append(field_name)
                        elif field_value.strip().upper() in ['INCOMPLETE', 'XX', 'N/A', 'TBD']:
                            incomplete_fields[field_name] = field_value

                    if missing_fields or incomplete_fields:
                        error_parts = []
                        if missing_fields:
                            error_parts.append(f"Missing: {', '.join(missing_fields)}")
                        if incomplete_fields:
                            error_parts.append(f"Incomplete: {', '.join(incomplete_fields.keys())}")

                        validation_errors.append({
                            'student': student_name,
                            'email': student_email,
                            'missing_fields': missing_fields,
                            'incomplete_fields': list(incomplete_fields.keys()),
                            'error': f"Incomplete billing contact. {' | '.join(error_parts)}. Please update student information in Student Management."
                        })

            except User.DoesNotExist:
                # New student - will be created, so skip validation for now
                # Will create with placeholder contact that must be updated before invoice approval
                pass

        # If validation errors found, return them with helpful message
        if validation_errors:
            return Response({
                'error': 'Cannot submit invoice - some students have incomplete billing information',
                'details': validation_errors,
                'message': 'Please update student billing information in Student Management before submitting this invoice. All fields (name, email, phone, street address, city, province, postal code) are required.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Create lessons and collect them for the invoice
        created_lessons = []

        for lesson_data in lessons_data:
            # Handle student lookup/creation
            student_name = lesson_data.get('student_name')
            student_email = lesson_data.get('student_email')

            if student_email:
                # Find or create student by email using get_or_create for atomicity
                student, created = User.objects.get_or_create(
                    email=student_email,
                    user_type='student',
                    defaults={
                        'first_name': student_name.split()[0] if student_name else '',
                        'last_name': ' '.join(student_name.split()[1:]) if student_name and len(student_name.split()) > 1 else '',
                        'is_approved': True,  # Auto-approve students created by teachers
                        'school': request.user.school  # Auto-assign teacher's school
                    }
                )
            else:
                # Create student with just name (no email)
                # Generate temp email and use get_or_create for atomicity
                temp_email = f"noemail_{uuid.uuid4().hex[:12]}@maplekeymusic.internal"
                student, created = User.objects.get_or_create(
                    email=temp_email,
                    user_type='student',
                    defaults={
                        'first_name': student_name.split()[0] if student_name else '',
                        'last_name': ' '.join(student_name.split()[1:]) if student_name and len(student_name.split()) > 1 else '',
                        'is_approved': True,
                        'school': request.user.school  # Auto-assign teacher's school
                    }
                )

            # If student was just created, create a placeholder billable contact
            # Management must complete this information before approving the invoice
            if created:
                # Handle both old 'state' and new 'province' field names for backward compatibility
                contact_data = {
                    'student': student,
                    'school': request.user.school,  # Auto-assign teacher's school
                    'contact_type': 'parent',
                    'first_name': 'INCOMPLETE',
                    'last_name': 'INCOMPLETE',
                    'email': student_email or temp_email,
                    'phone': 'INCOMPLETE',
                    'street_address': 'INCOMPLETE - Please update in Student Management',
                    'city': 'INCOMPLETE',
                    'postal_code': 'INCOMPLETE',
                    'is_primary': True
                }

                # Detect which field name to use (province vs state) for backward compatibility
                try:
                    BillableContact._meta.get_field('province')
                    contact_data['province'] = 'XX'
                except:
                    contact_data['state'] = 'XX'

                BillableContact.objects.create(**contact_data)

            # Create lesson with dual-rate system
            lesson_type = lesson_data.get('lesson_type', 'in_person')  # Default to in_person for backward compatibility

            # Determine rates based on lesson type using SchoolSettings
            from billing.models import SchoolSettings
            from decimal import Decimal

            # Get rates from school settings (with fallback to legacy GlobalRateSettings if needed)
            try:
                school_settings = SchoolSettings.get_settings_for_school(request.user.school)
                if lesson_type == 'online':
                    # Online lessons use school rates
                    teacher_rate = school_settings.online_teacher_rate
                    student_rate = school_settings.online_student_rate
                else:
                    # In-person lessons: teacher gets their hourly_rate, student pays school in-person rate
                    teacher_rate = request.user.hourly_rate
                    student_rate = school_settings.inperson_student_rate
            except Exception as e:
                # Fallback to legacy GlobalRateSettings for backward compatibility
                from billing.models import GlobalRateSettings
                logger.warning(f"Failed to load SchoolSettings, falling back to GlobalRateSettings: {e}")
                global_rates = GlobalRateSettings.get_settings()
                if lesson_type == 'online':
                    teacher_rate = global_rates.online_teacher_rate
                    student_rate = global_rates.online_student_rate
                else:
                    teacher_rate = request.user.hourly_rate
                    student_rate = global_rates.inperson_student_rate


            # Determine trial status
            if 'is_trial' in lesson_data:
                # Teacher explicitly set trial status - respect their choice
                is_trial = lesson_data.get('is_trial', False)
                explicitly_set = True
                logger.info(f"Teacher explicitly set is_trial={is_trial} for student {student.email}")
            else:
                # No explicit setting - auto-detect based on student history
                if not Lesson.student_has_completed_lesson(student):
                    is_trial = True
                    logger.info(f"Auto-detected first lesson for student {student.email} - marking as trial")
                else:
                    is_trial = False
                explicitly_set = False

            if is_trial:
                student_rate = Decimal('0.00')
                logger.info(f"Trial lesson for {student.email} - student_rate=$0.00, teacher_rate={teacher_rate}")

            # Create lesson
            lesson = Lesson(
                teacher=request.user,
                student=student,
                school=request.user.school,  # Auto-assign teacher's school
                lesson_type=lesson_type,
                is_trial=is_trial,
                scheduled_date=lesson_data.get('scheduled_date', timezone.now()),
                duration=lesson_data.get('duration', 1.0),
                teacher_rate=teacher_rate,
                student_rate=student_rate,
                status='completed',  # Mark as completed since teacher is submitting for payment
                completed_date=timezone.now(),
                teacher_notes=lesson_data.get('teacher_notes', '')
            )

            # Mark if trial status was explicitly set (to prevent auto-detection override in save())
            if explicitly_set:
                lesson._is_trial_explicitly_set = True

            # Save the lesson
            lesson.save()

            created_lessons.append(lesson)

        # Create invoice
        invoice = Invoice.objects.create(
            invoice_type='teacher_payment',
            teacher=request.user,
            school=request.user.school,  # Auto-assign teacher's school
            status='pending',  # Ready for management approval
            due_date=data.get('due_date', timezone.now() + timezone.timedelta(days=14)),  # 2 weeks
            created_by=request.user,
            payment_balance=0  # Will be calculated after lessons are added
        )

        # Add lessons to invoice
        invoice.lessons.set(created_lessons)

        # Recalculate payment balance and total amount
        calculated_total = invoice.calculate_payment_balance()
        invoice.payment_balance = calculated_total
        invoice.total_amount = calculated_total
        invoice.save()

        # Create student invoices
        # Group lessons by student
        from collections import defaultdict
        lessons_by_student = defaultdict(list)
        for lesson in created_lessons:
            lessons_by_student[lesson.student].append(lesson)

        student_invoices_created = []
        for student, student_lessons in lessons_by_student.items():
            # Calculate total for this student using student_rate (not teacher_rate)
            student_total = sum(lesson.student_cost() for lesson in student_lessons)

            # Create student invoice
            student_invoice = Invoice.objects.create(
                invoice_type='student_billing',
                student=student,
                school=request.user.school,  # Auto-assign teacher's school
                status='pending',  # Waiting for student payment
                due_date=timezone.now() + timezone.timedelta(days=14),  # 14 days payment term
                created_by=request.user,
                payment_balance=student_total,
                total_amount=student_total
            )

            # Add lessons to student invoice
            student_invoice.lessons.set(student_lessons)
            student_invoices_created.append(student_invoice)

        # Return the created invoice with lesson details
        serializer = InvoiceSerializer(invoice)
        return Response({
            'message': 'Lessons submitted and invoice created successfully',
            'invoice': serializer.data,
            'lessons_created': len(created_lessons),
            'student_invoices_created': len(student_invoices_created)
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        import traceback
        logger.error(f"Invoice submission failed: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return Response({
            'error': 'Failed to create invoice',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@management_required
def approve_teacher_invoice(request, invoice_id):
    """Management approves teacher payment invoices"""
    try:
        invoice = Invoice.objects.get(id=invoice_id, invoice_type='teacher_payment', school=request.user.school)
        invoice.status = 'approved'
        invoice.approved_by = request.user
        invoice.approved_at = timezone.now()
        invoice.save()
        return Response({'message': 'Invoice approved'})
    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

# ============================================================================
# MONTHLY INVOICE BATCH ENDPOINTS (Teacher Workflow)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def teacher_assigned_students(request):
    """Get all students assigned to the current teacher (teacher-only endpoint)"""
    if request.user.user_type != 'teacher':
        return Response({'error': 'Teacher access required'}, status=status.HTTP_403_FORBIDDEN)

    # Get active students assigned to this teacher
    students = request.user.assigned_students.filter(is_active=True)
    serializer = UserSerializer(students, many=True)

    return Response(serializer.data)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def teacher_monthly_batches(request):
    """
    This function handles two main jobs:
    1. GET: Fetching historical batches.
    2. POST: The "Smart" generation of a new monthly invoice.
    """

    # --- PART 1: RETRIEVING DATA ---
    if request.method == 'GET':
        # 1. Query the Database: Look for batches matching the logged-in user.
        # We use request.user (the teacher) to ensure they can't see other people's money!
        batches = MonthlyInvoiceBatch.objects.filter(
            teacher=request.user,
            school=request.user.school
        )

        # Filter by month/year if provided in query params (for get-or-create behavior)
        month = request.query_params.get('month')
        year = request.query_params.get('year')
        if month and year:
            batches = batches.filter(month=int(month), year=int(year))
        else:
            # If no filters, return all batches sorted
            batches = batches.order_by('-year', '-month')

        # 2. Translate to JSON: Since 'batches' is a list (QuerySet), we use many=True.
        serializer = MonthlyInvoiceBatchSerializer(batches, many=True)

        # 3. Send back to the Frontend.
        return Response(serializer.data)

    # --- PART 2: CREATING / INITIALIZING DATA ---
    elif request.method == 'POST':
        # 1. Capture user input: What month/year is the teacher trying to bill for?
        month = request.data.get('month')
        year = request.data.get('year')

        # 2. Validation: If they forgot the month/year, stop the process here.
        if not month or not year:
            return Response(
                {'error': 'month and year are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. The "Find or Create" logic:
        # 'batch' = the actual object (the row in the DB).
        # 'created' = a True/False flag telling us if it's brand new.
        batch, created = MonthlyInvoiceBatch.objects.get_or_create(
            teacher=request.user,
            school=request.user.school,
            month=month,
            year=year,
            defaults={'status': 'draft'} # If creating, set status to 'draft'
        )

        # 4. Automation: Sync lessons from recurring schedules
        # IMPORTANT: This now runs EVERY time (not just when created=True)
        # to ensure new recurring schedules added mid-month appear in existing batches

        # Get all expected lessons from active recurring schedules
        scheduled_lessons = batch.get_scheduled_lessons_data()

        # For each expected lesson, check if it already exists in the batch
        for lesson_data in scheduled_lessons:
            # Check if this lesson already exists (same student, date, time)
            existing_lesson = BatchLessonItem.objects.filter(
                batch=batch,
                student=lesson_data['student'],
                scheduled_date=lesson_data['scheduled_date'],
                start_time=lesson_data['start_time'],
            ).first()

            # Only create if it doesn't already exist (preserves manual edits)
            if not existing_lesson:
                # Auto-default trial: first lesson for a student (no prior Lesson records)
                item_status = lesson_data['status']
                student = lesson_data['student']
                prior_lesson_count = Lesson.objects.filter(student=student).count()
                if prior_lesson_count == 0:
                    item_status = 'trial'

                BatchLessonItem.objects.create(
                    batch=batch,
                    student=student,
                    scheduled_date=lesson_data['scheduled_date'],
                    start_time=lesson_data['start_time'],
                    duration=lesson_data['duration'],
                    lesson_type=lesson_data['lesson_type'],
                    teacher_rate=lesson_data['teacher_rate'],
                    student_rate=lesson_data['student_rate'],
                    status=item_status,
                    recurring_schedule=lesson_data['recurring_schedule'],
                    is_one_off=False
                )

        # 5. Translation: Now that the batch (and its items) exist in the DB,
        # we pass the 'batch' object to the Serializer to turn it into JSON.
        serializer = MonthlyInvoiceBatchSerializer(batch)

        # 6. Final Response: Return the data and the appropriate status code.
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def batch_detail(request, batch_id):
    """
    GET: Retrieve batch with all lesson items
    PUT: Update batch (only if status=draft)
    DELETE: Delete batch (only if status=draft)
    """
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            teacher=request.user,
            school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response(
            {'error': 'Batch not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = MonthlyInvoiceBatchSerializer(batch)
        return Response(serializer.data)

    elif request.method == 'PUT':
        if batch.status != 'draft':
            return Response(
                {'error': 'Cannot edit batch that is not in draft status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = MonthlyInvoiceBatchSerializer(batch, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        if batch.status != 'draft':
            return Response(
                {'error': 'Cannot delete batch that is not in draft status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        batch.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def batch_add_lesson(request, batch_id):
    """Add a one-off lesson to a draft batch"""
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            teacher=request.user,
            school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    if batch.status != 'draft':
        return Response(
            {'error': 'Cannot add lessons to non-draft batch'},
            status=status.HTTP_400_BAD_REQUEST
        )

    data = request.data.copy()
    data['is_one_off'] = True

    # Auto-populate rates based on lesson type if not provided
    if 'teacher_rate' not in data or 'student_rate' not in data:
        lesson_type = data.get('lesson_type', 'in_person')
        global_settings = GlobalRateSettings.get_settings()

        if lesson_type == 'online':
            data['teacher_rate'] = global_settings.online_teacher_rate
            data['student_rate'] = global_settings.online_student_rate
        else:  # in_person
            data['teacher_rate'] = request.user.hourly_rate or global_settings.online_teacher_rate
            data['student_rate'] = global_settings.inperson_student_rate

    # Auto-default trial: first lesson for a student (no prior Lesson records)
    student_id = data.get('student_id') or data.get('student')
    if student_id:
        try:
            student_obj = User.objects.get(id=student_id)
            prior_lesson_count = Lesson.objects.filter(student=student_obj).count()
            if prior_lesson_count == 0:
                data['status'] = 'trial'
        except Exception:
            pass

    serializer = BatchLessonItemSerializer(data=data)
    if serializer.is_valid():
        serializer.save(batch=batch)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def batch_lesson_item(request, batch_id, item_id):
    """
    PUT: Update a lesson item's status/notes (teacher marks completed/cancelled)
    DELETE: Remove a one-off lesson item only
    """
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            teacher=request.user,
            school=request.user.school
        )
        item = batch.lesson_items.get(id=item_id)
    except (MonthlyInvoiceBatch.DoesNotExist, BatchLessonItem.DoesNotExist):
        return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)

    if batch.status != 'draft':
        return Response(
            {'error': 'Cannot modify non-draft batch'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if request.method == 'PUT':
        allowed_fields = ['status', 'cancelled_by_type', 'cancellation_reason', 'teacher_notes']
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}

        serializer = BatchLessonItemSerializer(item, data=update_data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        if not item.is_one_off:
            return Response(
                {'error': 'Cannot delete recurring lessons. Mark as cancelled instead.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def batch_submit(request, batch_id):
    """Submit a draft batch for management review"""
    try:
        batch = MonthlyInvoiceBatch.objects.get(
            id=batch_id,
            teacher=request.user,
            school=request.user.school
        )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    if batch.status != 'draft':
        return Response(
            {'error': 'Batch already submitted'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if batch.lesson_items.count() == 0:
        return Response(
            {'error': 'Cannot submit empty batch'},
            status=status.HTTP_400_BAD_REQUEST
        )

    batch.status = 'submitted'
    batch.submitted_at = timezone.now()
    # Clear rejection reason when resubmitting after rejection
    batch.rejection_reason = ''
    batch.save()

    # TODO: Send email notification to management (Phase 5)

    serializer = MonthlyInvoiceBatchSerializer(batch)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_paystub(request, batch_id):
    """
    Download paystub PDF for approved batch.
    Teachers can download their own approved batches.
    Management can download any approved batch.
    """
    try:
        # Check if user is management
        is_management = request.user.user_type == 'management'

        if is_management:
            # Management can download any batch
            batch = MonthlyInvoiceBatch.objects.get(id=batch_id)
        else:
            # Teachers can only download their own batches
            batch = MonthlyInvoiceBatch.objects.get(
                id=batch_id,
                teacher=request.user
            )
    except MonthlyInvoiceBatch.DoesNotExist:
        return Response({'error': 'Batch not found'}, status=status.HTTP_404_NOT_FOUND)

    # Only approved batches can generate paystubs
    if batch.status != 'approved':
        return Response(
            {'error': 'Paystub only available for approved batches'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Generate PDF using TeacherPaystubPDFGenerator
    from billing.services.teacher_paystub_generator import TeacherPaystubPDFGenerator

    try:
        generator = TeacherPaystubPDFGenerator(batch)
        success, pdf_content = generator.generate_pdf()

        if not success or not pdf_content:
            return Response(
                {'error': 'Failed to generate paystub PDF'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Return PDF as download
        response = HttpResponse(pdf_content, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="paystub_{batch.batch_number}.pdf"'
        return response

    except Exception as e:
        logger.error(f"Error generating paystub for batch {batch_id}: {str(e)}")
        return Response(
            {'error': f'Failed to generate paystub: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
