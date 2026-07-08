from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords


class ScheduleInstrument(models.Model):
    """Instrument tag for a recurring schedule (analytics side-table).

    Lives here — NOT as a field on billing.RecurringLessonsSchedule — so the
    analytics feature adds zero billing migrations while Phase 19 is mid-flight
    on that app. A later GSD phase may fold this into billing proper; the
    OneToOne makes that migration trivial.
    """
    schedule = models.OneToOneField(
        'billing.RecurringLessonsSchedule',
        on_delete=models.CASCADE,
        related_name='instrument_tag',
    )
    instrument = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Schedule {self.schedule_id} — {self.instrument}"


class ExpenseItemCategory(models.Model):
    """Category tag for an expense line item (analytics side-table).

    Same rationale as ScheduleInstrument: keeps billing migrations untouched.
    'advertising' is the category the CPA metric consumes.
    """
    CATEGORY_CHOICES = [
        ('advertising', 'Advertising'),
        ('payroll', 'Payroll (non-teacher)'),
        ('infrastructure', 'Digital Infrastructure'),
        ('rent', 'Rent & Facilities'),
        ('supplies', 'Supplies & Equipment'),
        ('other', 'Other'),
    ]

    expense_item = models.OneToOneField(
        'billing.SchoolExpenseItem',
        on_delete=models.CASCADE,
        related_name='category_tag',
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'expense item categories'

    def __str__(self):
        return f"Expense {self.expense_item_id} — {self.get_category_display()}"


class StudentExitRecord(models.Model):
    """Why a student left — captured when management deactivates a student.

    Feeds the reason-for-leaving retention metric. Deliberately decoupled from
    the deactivation endpoint (billing) — the frontend records this separately
    right after a successful deactivation.
    """
    REASON_CHOICES = [
        ('schedule_conflict', 'Schedule Conflict'),
        ('price', 'Price'),
        ('moved', 'Moved Away'),
        ('teacher_fit', 'Teacher Fit'),
        ('lost_interest', 'Lost Interest'),
        ('finished_goals', 'Finished Goals'),
        ('other', 'Other'),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='exit_records',
        limit_choices_to={'user_type': 'student'},
    )
    school = models.ForeignKey(
        'billing.School',
        on_delete=models.PROTECT,
        related_name='student_exit_records',
    )
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    notes = models.TextField(blank=True, default='')
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recorded_exit_records',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.school_id and self.student_id:
            self.school = self.student.school
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student.get_full_name()} left — {self.get_reason_display()}"


class MetricGoal(models.Model):
    """A management-set target for a dashboard metric."""
    METRIC_CHOICES = [
        ('mrr', 'Monthly Recurring Revenue'),
        ('gross_margin', 'Gross Margin'),
        ('active_students', 'Active Students'),
        ('new_enrollments', 'New Enrollments / Month'),
        ('churn_rate', 'Churn Rate %'),
        ('trial_conversion', 'Trial Conversion %'),
    ]

    school = models.ForeignKey(
        'billing.School',
        on_delete=models.CASCADE,
        related_name='metric_goals',
    )
    metric = models.CharField(max_length=30, choices=METRIC_CHOICES)
    target = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_metric_goals',
    )
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['school', 'metric'],
                name='unique_goal_per_school_metric',
            ),
        ]

    def __str__(self):
        return f"{self.school.name}: {self.get_metric_display()} → {self.target}"
