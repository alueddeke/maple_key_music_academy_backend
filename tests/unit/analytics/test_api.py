"""Endpoint + permission tests for analytics views."""

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from analytics.models import (
    ExpenseItemCategory,
    MetricGoal,
    ScheduleInstrument,
    StudentExitRecord,
)
from billing.models import SchoolExpenseItem


@pytest.mark.django_db
class TestOverviewEndpoint:
    def test_management_gets_overview_shape(self, management_client, active_schedule):
        response = management_client.get(reverse('analytics_overview'))
        assert response.status_code == status.HTTP_200_OK
        assert set(response.data.keys()) == {'months', 'current', 'goals'}
        assert len(response.data['months']) == 6  # default window
        assert 'mrr' in response.data['current']
        assert 'overdue_invoices' in response.data['current']

    def test_months_param_clamped(self, management_client):
        response = management_client.get(reverse('analytics_overview') + '?months=99')
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['months']) == 24

    def test_months_param_invalid(self, management_client):
        response = management_client.get(reverse('analytics_overview') + '?months=abc')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_teacher_forbidden(self, teacher_client):
        response = teacher_client.get(reverse('analytics_overview'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_student_forbidden(self, student_client):
        response = student_client.get(reverse('analytics_overview'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_rejected(self, api_client):
        response = api_client.get(reverse('analytics_overview'))
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


@pytest.mark.django_db
class TestGoalsEndpoint:
    def test_put_replaces_goal_list(self, management_client, school):
        payload = [
            {'metric': 'mrr', 'target': '5000.00'},
            {'metric': 'active_students', 'target': '40'},
        ]
        response = management_client.put(
            reverse('analytics_goals'), payload, format='json'
        )
        assert response.status_code == status.HTTP_200_OK
        assert MetricGoal.objects.filter(school=school).count() == 2

        # PUT with one goal removes the other
        response = management_client.put(
            reverse('analytics_goals'),
            [{'metric': 'mrr', 'target': '6000.00'}],
            format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        goals = MetricGoal.objects.filter(school=school)
        assert goals.count() == 1
        assert goals.first().target == Decimal('6000.00')

    def test_put_invalid_metric_rejected(self, management_client):
        response = management_client.put(
            reverse('analytics_goals'),
            [{'metric': 'nonsense', 'target': '1'}],
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_non_list_rejected(self, management_client):
        response = management_client.put(
            reverse('analytics_goals'), {'metric': 'mrr'}, format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_teacher_forbidden(self, teacher_client):
        response = teacher_client.get(reverse('analytics_goals'))
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestScheduleInstrumentEndpoint:
    def test_put_sets_and_clears_tag(self, management_client, active_schedule):
        url = reverse(
            'analytics_schedule_instrument_detail',
            kwargs={'schedule_id': active_schedule.id},
        )
        response = management_client.put(url, {'instrument': 'Piano'}, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert ScheduleInstrument.objects.get(
            schedule=active_schedule
        ).instrument == 'Piano'

        response = management_client.put(url, {'instrument': ''}, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert not ScheduleInstrument.objects.filter(
            schedule=active_schedule
        ).exists()

    def test_list_filter_by_student(
        self, management_client, active_schedule, student_user
    ):
        ScheduleInstrument.objects.create(
            schedule=active_schedule, instrument='Violin'
        )
        response = management_client.get(
            reverse('analytics_schedule_instruments')
            + f'?student_id={student_user.id}'
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data == [
            {'schedule_id': active_schedule.id, 'instrument': 'Violin'}
        ]

    def test_cross_school_schedule_404(
        self, api_client, second_school, active_schedule
    ):
        from django.contrib.auth import get_user_model
        other_mgmt = get_user_model().objects.create_user(
            email='mgmt2@test.com', password='x', user_type='management',
            school=second_school, is_approved=True,
        )
        api_client.force_authenticate(user=other_mgmt)
        response = api_client.put(
            reverse(
                'analytics_schedule_instrument_detail',
                kwargs={'schedule_id': active_schedule.id},
            ),
            {'instrument': 'Piano'},
            format='json',
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestExpenseCategoryEndpoint:
    @pytest.fixture
    def expense_item(self, school, db):
        from datetime import date
        return SchoolExpenseItem.objects.create(
            school=school,
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            title='Google Ads',
            amount=Decimal('120.00'),
        )

    def test_put_sets_category(self, management_client, expense_item):
        url = reverse(
            'analytics_expense_category',
            kwargs={'expense_item_id': expense_item.id},
        )
        response = management_client.put(
            url, {'category': 'advertising'}, format='json'
        )
        assert response.status_code == status.HTTP_200_OK
        assert ExpenseItemCategory.objects.get(
            expense_item=expense_item
        ).category == 'advertising'

    def test_invalid_category_rejected(self, management_client, expense_item):
        url = reverse(
            'analytics_expense_category',
            kwargs={'expense_item_id': expense_item.id},
        )
        response = management_client.put(url, {'category': 'snacks'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_categorized_ad_spend_feeds_cpa(
        self, management_client, expense_item, school, student_user, teacher_user
    ):
        # tag as advertising, then CPA = 120 / 1 new enrollment in window
        ExpenseItemCategory.objects.create(
            expense_item=expense_item, category='advertising'
        )
        from analytics.services import compute_current_metrics
        from datetime import date
        current = compute_current_metrics(school, today=date(2026, 6, 15))
        # student_user's trial lesson (~30 days before now, i.e. within window)
        assert current['cpa'] is not None


@pytest.mark.django_db
class TestExitRecordEndpoint:
    def test_post_creates_record(self, management_client, student_user):
        response = management_client.post(
            reverse('analytics_exit_records'),
            {'student': student_user.id, 'reason': 'moved', 'notes': 'Toronto → BC'},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        record = StudentExitRecord.objects.get(student=student_user)
        assert record.reason == 'moved'
        assert record.school == student_user.school

    def test_invalid_reason_rejected(self, management_client, student_user):
        response = management_client.post(
            reverse('analytics_exit_records'),
            {'student': student_user.id, 'reason': 'aliens'},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_student_404(self, management_client):
        response = management_client.post(
            reverse('analytics_exit_records'),
            {'student': 999999, 'reason': 'moved'},
            format='json',
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_teacher_forbidden(self, teacher_client, student_user):
        response = teacher_client.post(
            reverse('analytics_exit_records'),
            {'student': student_user.id, 'reason': 'moved'},
            format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
