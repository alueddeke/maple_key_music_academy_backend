from django.contrib import admin

from .models import (
    ExpenseItemCategory,
    MetricGoal,
    ScheduleInstrument,
    StudentExitRecord,
)


@admin.register(ScheduleInstrument)
class ScheduleInstrumentAdmin(admin.ModelAdmin):
    list_display = ('schedule', 'instrument', 'updated_at')
    search_fields = ('instrument',)


@admin.register(ExpenseItemCategory)
class ExpenseItemCategoryAdmin(admin.ModelAdmin):
    list_display = ('expense_item', 'category', 'updated_at')
    list_filter = ('category',)


@admin.register(StudentExitRecord)
class StudentExitRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'reason', 'recorded_by', 'created_at')
    list_filter = ('reason',)
    search_fields = ('student__email',)


@admin.register(MetricGoal)
class MetricGoalAdmin(admin.ModelAdmin):
    list_display = ('school', 'metric', 'target', 'updated_by', 'updated_at')
    list_filter = ('metric',)
