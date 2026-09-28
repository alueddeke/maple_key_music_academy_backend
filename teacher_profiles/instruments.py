"""A teacher's instrument list as one display string (MAP-229).

TeacherInstrument rows are the only instrument store. API payloads that
predate the rows keep their `instruments` key as a read-only string built
here, so display code reads the same shape it always has.
"""
from .models import TeacherProfile


def instrument_names(user):
    """Row names joined with ', ' in model ordering; '' for non-teachers or no profile."""
    if user.user_type != 'teacher':
        return ''
    try:
        profile = user.teacher_profile
    except TeacherProfile.DoesNotExist:
        return ''
    return ', '.join(row.instrument for row in profile.instruments.all())
