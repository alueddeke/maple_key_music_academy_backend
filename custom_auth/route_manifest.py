"""
Route-auth manifest (MAP-143): every URL route must declare who may call it.

Keyed by route name (namespaced as `namespace:name` where the include has a
namespace). Values:

- PUBLIC: reachable without authentication. Adding a route here is a
  deliberate decision that the endpoint is open to the internet.
- INFRA: framework/observability mounts (Django admin, health check,
  Prometheus) that are guarded outside DRF and not exercised by the test.
- frozenset of roles from {'student', 'teacher', 'management'}: the
  `User.user_type` values allowed through the auth gate.

tests/integration/custom_auth/test_route_auth_manifest.py drives every route
through the real stack and fails when a route is missing here, when an entry
here no longer resolves, or when the observed status disagrees with the entry.
scripts/route_role_matrix.py renders this table for security review.
"""
import inspect
import os

from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver

PUBLIC = 'PUBLIC'
INFRA = 'INFRA'

STUDENT = 'student'
TEACHER = 'teacher'
MANAGEMENT = 'management'

ALL_ROLES = frozenset({STUDENT, TEACHER, MANAGEMENT})
TEACHER_ONLY = frozenset({TEACHER})
MANAGEMENT_ONLY = frozenset({MANAGEMENT})
TEACHER_OR_MANAGEMENT = frozenset({TEACHER, MANAGEMENT})

# Namespaces whose routes are not walked; the whole namespace is one entry.
OPAQUE_NAMESPACES = ('admin',)

HTTP_METHODS = ('get', 'post', 'put', 'patch', 'delete')

ROUTE_MANIFEST = {
    # --- infrastructure (maple_key_backend/urls.py) ---
    'admin': INFRA,
    'health_check:health_check_home': INFRA,
    'health_check:health_check_subset': INFRA,
    'prometheus-django-metrics': INFRA,

    # --- custom_auth/urls.py ---
    'google_exchange': PUBLIC,
    'register_with_email': PUBLIC,
    'get_jwt_token': PUBLIC,
    'refresh_jwt_token': PUBLIC,
    'user_profile': ALL_ROLES,
    'logout': PUBLIC,
    'report_client_error': PUBLIC,
    'password_reset_request': PUBLIC,
    'password_reset_validate': PUBLIC,
    'password_reset_confirm': PUBLIC,

    # --- billing/urls.py ---
    'teacher_invoice_stats': TEACHER_ONLY,
    'submit_lessons_for_invoice': TEACHER_ONLY,
    'approved_email_list': MANAGEMENT_ONLY,
    'approved_email_delete': MANAGEMENT_ONLY,
    'registration_request_list': MANAGEMENT_ONLY,
    'approve_registration_request': MANAGEMENT_ONLY,
    'reject_registration_request': MANAGEMENT_ONLY,
    'management_all_users': MANAGEMENT_ONLY,
    'management_delete_user': MANAGEMENT_ONLY,
    'validate_invitation_token': PUBLIC,
    'setup_account_with_invitation': PUBLIC,
    'waive_policy_settings': MANAGEMENT_ONLY,
    'student_waive_usage': TEACHER_OR_MANAGEMENT,
    'list_invoice_recipients': MANAGEMENT_ONLY,
    'add_invoice_recipient': MANAGEMENT_ONLY,
    'delete_invoice_recipient': MANAGEMENT_ONLY,
    'global_rate_settings': MANAGEMENT_ONLY,
    'management_teacher_list': MANAGEMENT_ONLY,
    'management_teacher_detail': MANAGEMENT_ONLY,
    'get_current_school': MANAGEMENT_ONLY,
    'update_school': MANAGEMENT_ONLY,
    'school_settings': MANAGEMENT_ONLY,
    'management_students': MANAGEMENT_ONLY,
    'management_student_detail': MANAGEMENT_ONLY,
    'add_billable_contact': MANAGEMENT_ONLY,
    'manage_billable_contact': MANAGEMENT_ONLY,
    'student_recurring_schedules': MANAGEMENT_ONLY,
    'recurring_schedule_detail': MANAGEMENT_ONLY,
    'student_pause_lessons': MANAGEMENT_ONLY,
    'assign_teachers_to_student': MANAGEMENT_ONLY,
    'unassign_teacher_from_student': MANAGEMENT_ONLY,
    'teacher_students': MANAGEMENT_ONLY,
    'management_teacher_invoices': MANAGEMENT_ONLY,
    'management_update_teacher': MANAGEMENT_ONLY,
    'management_delete_teacher': MANAGEMENT_ONLY,
    'teacher_assigned_students': TEACHER_ONLY,
    'teacher_monthly_batches': TEACHER_OR_MANAGEMENT,
    'batch_detail': TEACHER_OR_MANAGEMENT,
    'batch_add_lesson': TEACHER_ONLY,
    'batch_lesson_item': TEACHER_ONLY,
    'batch_submit': TEACHER_ONLY,
    'download_paystub': TEACHER_OR_MANAGEMENT,
    'teacher_batch_adjustment_item': TEACHER_ONLY,
    'management_pending_batches': MANAGEMENT_ONLY,
    'management_approved_batches': MANAGEMENT_ONLY,
    'management_rejected_batches': MANAGEMENT_ONLY,
    'management_month_end_queue': MANAGEMENT_ONLY,
    'management_batch_detail': MANAGEMENT_ONLY,
    'management_edit_lesson_notes': MANAGEMENT_ONLY,
    'management_approve_batch': MANAGEMENT_ONLY,
    'management_reject_batch': MANAGEMENT_ONLY,
    'management_batch_rejection_snapshots': MANAGEMENT_ONLY,
    'management_delete_rejected_batch': MANAGEMENT_ONLY,
    'management_archive_month': MANAGEMENT_ONLY,
    'management_archived_batches': MANAGEMENT_ONLY,
    'management_unarchive_batch': MANAGEMENT_ONLY,
    'management_generate_teacher_invoice': MANAGEMENT_ONLY,
    'payment_callback': PUBLIC,
    'management_pre_billing_generate': MANAGEMENT_ONLY,
    'management_pre_billing_send_all': MANAGEMENT_ONLY,
    'management_send_run_latest': MANAGEMENT_ONLY,
    'management_send_run_detail': MANAGEMENT_ONLY,
    'management_send_run_cancel': MANAGEMENT_ONLY,
    'management_pre_billing_list': MANAGEMENT_ONLY,
    'management_pre_billing_detail': MANAGEMENT_ONLY,
    'management_pre_billing_send': MANAGEMENT_ONLY,
    'management_pre_billing_remove_lesson': MANAGEMENT_ONLY,
    'management_pre_billing_resend_email': MANAGEMENT_ONLY,
    'management_pre_billing_skip_date': MANAGEMENT_ONLY,
    'management_pre_billing_restore_date': MANAGEMENT_ONLY,
    'management_dashboard_batches': MANAGEMENT_ONLY,
    'management_dashboard_data': MANAGEMENT_ONLY,
    'management_patch_invoice': MANAGEMENT_ONLY,
    'management_upsert_expenses': MANAGEMENT_ONLY,
    'management_expense_items': MANAGEMENT_ONLY,
    'management_expense_item_delete': MANAGEMENT_ONLY,

    # --- teacher_profiles/urls.py ---
    'school_instrument_list': TEACHER_OR_MANAGEMENT,
    'school_instrument_create': MANAGEMENT_ONLY,
    'school_instrument_detail': MANAGEMENT_ONLY,
    'teacher_profile_detail': TEACHER_OR_MANAGEMENT,
    'teacher_instrument_list': TEACHER_OR_MANAGEMENT,
    'teacher_instrument_detail': TEACHER_OR_MANAGEMENT,
    'teacher_availability_list': TEACHER_OR_MANAGEMENT,
    'teacher_availability_detail': TEACHER_OR_MANAGEMENT,

    # --- notifications/urls.py ---
    'notification_list': TEACHER_OR_MANAGEMENT,
    'notification_mark_read': TEACHER_OR_MANAGEMENT,
    'notification_mark_all_read': TEACHER_OR_MANAGEMENT,
    'notification_preferences': TEACHER_OR_MANAGEMENT,

    # --- analytics/urls.py ---
    'analytics_overview': MANAGEMENT_ONLY,
    'analytics_goals': MANAGEMENT_ONLY,
    'analytics_schedule_instruments': MANAGEMENT_ONLY,
    'analytics_schedule_instrument_detail': MANAGEMENT_ONLY,
    'analytics_expense_category': MANAGEMENT_ONLY,
    'analytics_exit_records': MANAGEMENT_ONLY,
}


class Route:
    """One resolvable route: qualified name, path template, methods, callback."""

    def __init__(self, name, path, callback):
        self.name = name
        self.path = path
        self.callback = callback

    @property
    def methods(self):
        view_cls = getattr(self.callback, 'cls', None) or getattr(
            self.callback, 'view_class', None
        )
        if view_cls is None:
            return ()
        return tuple(m.upper() for m in HTTP_METHODS if hasattr(view_cls, m))

    def view_function(self):
        """The undecorated view function behind the callback.

        DRF's @api_view hides the function inside the generated APIView's
        method handlers (as the closure variable `func`); class-based views
        are returned as their class.
        """
        view_cls = getattr(self.callback, 'cls', None) or getattr(
            self.callback, 'view_class', None
        )
        if view_cls is None:
            return inspect.unwrap(self.callback)
        for method in HTTP_METHODS:
            handler = getattr(view_cls, method, None)
            if handler is None:
                continue
            func = inspect.getclosurevars(handler).nonlocals.get('func')
            if func is not None:
                return inspect.unwrap(func)
        return view_cls

    def source(self):
        """`path/to/file.py:line` of the view's def (decorators unwrapped)."""
        if self.callback is None:
            return ''
        func = self.view_function()
        try:
            filename = inspect.getsourcefile(func)
            _, line = inspect.getsourcelines(func)
        except (OSError, TypeError):
            return func.__module__
        relative = os.path.relpath(filename, settings.BASE_DIR)
        if relative.startswith('..'):
            return f'{func.__module__} (third-party)'
        return f'{relative}:{line}'


def iter_routes(patterns=None, prefix='', namespace=None):
    """Yield a Route for every named pattern in the project URLconf."""
    if patterns is None:
        patterns = get_resolver().url_patterns
    for entry in patterns:
        if isinstance(entry, URLResolver):
            ns = namespace
            if entry.namespace:
                ns = f'{namespace}:{entry.namespace}' if namespace else entry.namespace
            path = prefix + str(entry.pattern)
            if entry.namespace in OPAQUE_NAMESPACES:
                yield Route(ns, path, None)
                continue
            yield from iter_routes(entry.url_patterns, path, ns)
        elif isinstance(entry, URLPattern):
            name = f'{namespace}:{entry.name}' if namespace and entry.name else entry.name
            yield Route(name, prefix + str(entry.pattern), entry.callback)
