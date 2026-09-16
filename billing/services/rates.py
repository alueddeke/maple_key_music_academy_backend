"""
billing/services/rates.py — the single rate-resolution service (MAP-182).

Precedence:
    in_person -> (teacher.hourly_rate, school_settings.inperson_student_rate)
    online    -> (school_settings.online_teacher_rate, school_settings.online_student_rate)

SchoolSettings.get_settings_for_school(school) is the only settings source
(get_or_create, so it cannot be missing). The legacy global singleton is never read.
teacher.hourly_rate is used as stored.
"""
from billing.models import SchoolSettings


def resolve_rates(school, teacher, lesson_type):
    """Return (teacher_rate, student_rate) for a lesson of lesson_type."""
    school_settings = SchoolSettings.get_settings_for_school(school)
    if lesson_type == 'online':
        return school_settings.online_teacher_rate, school_settings.online_student_rate
    return teacher.hourly_rate, school_settings.inperson_student_rate
