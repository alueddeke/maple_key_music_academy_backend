"""
billing/services/rates.py — the single rate-resolution service (MAP-182).

Precedence:
    in_person -> (teacher.hourly_rate, school_settings.inperson_student_rate)
    online    -> (teacher.online_hourly_rate, or school_settings.online_teacher_rate
                  when it is None; school_settings.online_student_rate)

Two tiers only (MAP-163): an online rate never falls back to teacher.hourly_rate.
SchoolSettings.get_settings_for_school(school) is the only settings source
(get_or_create, so it cannot be missing). The legacy global singleton is never read.
Teacher rates are used as stored; 0 is a real rate, None means "unset".
"""
from billing.models import SchoolSettings


def resolve_rates(school, teacher, lesson_type):
    """Return (teacher_rate, student_rate) for a lesson of lesson_type."""
    school_settings = SchoolSettings.get_settings_for_school(school)
    if lesson_type == 'online':
        if teacher.online_hourly_rate is not None:
            return teacher.online_hourly_rate, school_settings.online_student_rate
        return school_settings.online_teacher_rate, school_settings.online_student_rate
    return teacher.hourly_rate, school_settings.inperson_student_rate
