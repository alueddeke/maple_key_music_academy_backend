"""
billing/services/rates.py — rate resolution for teacher-created lessons.

MAP-179 (D5): resolve_rates() is a VERBATIM move of the auto-fill block that
lived in billing/views/teacher.py::batch_add_lesson (baseline :678-697),
including the broad-except GlobalRateSettings fallback and its two quirks
(in-person teacher fallback to inperson_student_rate / online_teacher_rate).
Zero behaviour change is the contract of MAP-179; MAP-182 rewrites the
internals and moves the other rate call sites here.
"""
from billing.models import GlobalRateSettings


def resolve_rates(school, teacher, lesson_type):
    """Return (teacher_rate, student_rate) for a lesson of lesson_type."""
    try:
        from billing.models import SchoolSettings
        school_settings = SchoolSettings.get_settings_for_school(school)
        if lesson_type == 'online':
            teacher_rate = school_settings.online_teacher_rate
            student_rate = school_settings.online_student_rate
        else:  # in_person
            teacher_rate = teacher.hourly_rate or school_settings.inperson_student_rate
            student_rate = school_settings.inperson_student_rate
    except Exception:
        # Fallback to legacy GlobalRateSettings for backward compatibility
        global_settings = GlobalRateSettings.get_settings()
        if lesson_type == 'online':
            teacher_rate = global_settings.online_teacher_rate
            student_rate = global_settings.online_student_rate
        else:  # in_person
            teacher_rate = teacher.hourly_rate or global_settings.online_teacher_rate
            student_rate = global_settings.inperson_student_rate
    return teacher_rate, student_rate
