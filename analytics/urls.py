from django.urls import path

from . import views

urlpatterns = [
    path('overview/', views.analytics_overview, name='analytics_overview'),
    path('goals/', views.metric_goals, name='analytics_goals'),
    path(
        'schedule-instruments/',
        views.schedule_instrument_list,
        name='analytics_schedule_instruments',
    ),
    path(
        'schedule-instruments/<int:schedule_id>/',
        views.schedule_instrument_detail,
        name='analytics_schedule_instrument_detail',
    ),
    path(
        'expense-categories/<int:expense_item_id>/',
        views.expense_item_category,
        name='analytics_expense_category',
    ),
    path('exit-records/', views.create_exit_record, name='analytics_exit_records'),
]
