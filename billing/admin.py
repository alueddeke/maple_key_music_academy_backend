from django.contrib import admin
from .models import Invoice, Lesson, Student, Teacher

# Register your models here.

class LessonAdmin(admin.ModelAdmin):
    list_display = ['student', 'teacher', 'date', 'duration', 'rate', 'total_cost']
    list_filter = ['date', 'teacher', 'student']
    date_hierarchy = 'date'


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['teacher', 'date', 'paymentBalance', 'status', 'lesson_count']
    list_filter = ['status', 'date', 'teacher']
    readonly_fields = ['paymentBalance']
    
    def lesson_count(self, obj):
        return obj.lessons.count()
    lesson_count.short_description = 'Number of Lessons'


admin.site.register(Lesson, LessonAdmin)
admin.site.register(Student)
admin.site.register(Teacher)