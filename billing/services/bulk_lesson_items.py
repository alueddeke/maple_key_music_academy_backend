"""
billing/services/bulk_lesson_items.py — one status + one note on many batch
lesson items in a single all-or-nothing request (MAP-176).

Shared by the teacher route (draft batches) and the management route
(submitted batches). The views own auth, batch lookup and the batch-status
guard; this module owns the body rules, item lookup and the atomic write.

Body: {"item_ids": [int, ...], "status": str, <optional note fields>}.
- item_ids: non-empty list of distinct integers, at most BULK_LESSON_ITEMS_MAX
  -> otherwise 400 {"error": "..."}.
- status: required -> otherwise 400 {"error": "..."}.
- any id that is not an item of this batch -> 404, nothing changed.
- any row the serializer rejects (or a status outside allowed_statuses)
  -> 400 {"errors": {"<item_id>": {...}}}, nothing changed.
- success -> 200 {"updated": [serialized items, in item_ids order]}.
Keys outside `fields` are ignored, as on the single-item routes.
"""
from django.db import transaction
from rest_framework import status as http_status

from billing.serializers import BatchLessonItemSerializer

BULK_LESSON_ITEMS_MAX = 200


def _body_error(data):
    """Return an error message for a malformed body, or None."""
    item_ids = data.get('item_ids')
    if not isinstance(item_ids, list) or not item_ids:
        return 'item_ids must be a non-empty list'
    if not all(isinstance(i, int) and not isinstance(i, bool) for i in item_ids):
        return 'item_ids must contain integers only'
    if len(set(item_ids)) != len(item_ids):
        return 'item_ids must not contain duplicates'
    if len(item_ids) > BULK_LESSON_ITEMS_MAX:
        return f'At most {BULK_LESSON_ITEMS_MAX} items per request'
    if 'status' not in data:
        return 'status is required'
    return None


def _no_extra(update_data, item):
    return update_data, {}


def bulk_update_lesson_items(batch, data, fields, allowed_statuses=None, prepare=_no_extra):
    """
    Apply `fields` from `data` to every item in data['item_ids'] on `batch`.

    allowed_statuses: when given, a status outside it is a per-item error.
    prepare(update_data, item) -> (update_data, extra_response_keys) runs per
    item before validation, in item_ids order, inside the transaction (so a
    per-student count sees the rows already written by this request).

    Returns (http_status_code, response_body).
    """
    message = _body_error(data)
    if message:
        return http_status.HTTP_400_BAD_REQUEST, {'error': message}

    item_ids = data['item_ids']
    items = {item.id: item for item in batch.lesson_items.filter(id__in=item_ids)}
    if len(items) != len(item_ids):
        return http_status.HTTP_404_NOT_FOUND, {'error': 'Lesson item not found'}

    update_data = {k: data[k] for k in fields if k in data}

    if allowed_statuses is not None and update_data['status'] not in allowed_statuses:
        status_error = {'status': [f"Invalid status. Allowed values: {', '.join(allowed_statuses)}"]}
        return http_status.HTTP_400_BAD_REQUEST, {
            'errors': {str(item_id): status_error for item_id in item_ids}
        }

    errors = {}
    updated = []
    with transaction.atomic():
        for item_id in item_ids:
            item = items[item_id]
            row_data, extra = prepare(dict(update_data), item)
            serializer = BatchLessonItemSerializer(item, data=row_data, partial=True)
            if not serializer.is_valid():
                errors[str(item_id)] = serializer.errors
            elif not errors:
                serializer.save()
                updated.append(dict(serializer.data) | extra)
        if errors:
            transaction.set_rollback(True)

    if errors:
        return http_status.HTTP_400_BAD_REQUEST, {'errors': errors}
    return http_status.HTTP_200_OK, {'updated': updated}
