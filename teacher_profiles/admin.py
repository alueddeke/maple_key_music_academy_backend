from django.contrib import admin

from .models import TeacherAvailability, TeacherInstrument, TeacherProfile


class TeacherInstrumentInline(admin.TabularInline):
    model = TeacherInstrument
    extra = 0


class TeacherAvailabilityInline(admin.TabularInline):
    model = TeacherAvailability
    extra = 0


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'school', 'teachable_area', 'updated_at')
    search_fields = ('teacher__email', 'teacher__first_name', 'teacher__last_name')
    inlines = [TeacherInstrumentInline, TeacherAvailabilityInline]


@admin.register(TeacherInstrument)
class TeacherInstrumentAdmin(admin.ModelAdmin):
    list_display = ('profile', 'instrument', 'skill_ceiling', 'rate',
                    'teaches_theory', 'teaches_history', 'teaches_rcm_prep')
    list_filter = ('skill_ceiling', 'teaches_theory', 'teaches_history', 'teaches_rcm_prep')


@admin.register(TeacherAvailability)
class TeacherAvailabilityAdmin(admin.ModelAdmin):
    list_display = ('profile', 'day_of_week', 'start_time', 'end_time')
    list_filter = ('day_of_week',)
