from django.urls import path

from . import views

urlpatterns = [
    path(
        '<int:teacher_id>/',
        views.teacher_profile_detail,
        name='teacher_profile_detail',
    ),
    path(
        '<int:teacher_id>/instruments/',
        views.teacher_instrument_list,
        name='teacher_instrument_list',
    ),
    path(
        '<int:teacher_id>/instruments/<int:instrument_id>/',
        views.teacher_instrument_detail,
        name='teacher_instrument_detail',
    ),
    path(
        '<int:teacher_id>/availability/',
        views.teacher_availability_list,
        name='teacher_availability_list',
    ),
    path(
        '<int:teacher_id>/availability/<int:slot_id>/',
        views.teacher_availability_detail,
        name='teacher_availability_detail',
    ),
]
