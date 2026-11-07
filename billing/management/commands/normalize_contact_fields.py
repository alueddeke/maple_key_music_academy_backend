"""
Store already-saved phones and postal codes in the canonical form (MAP-293).

New input is normalized by the serializers (billing/serializers.py). This
one-off command brings the rows saved before that into line:

  phone        -> 10 digits (a leading 1 on 11 digits dropped)
  postal code  -> A1A 1A1

Covers User (phone_number, postal_code), BillableContact (phone,
postal_code) and School (phone_number, postal_code). Blank values stay
blank. A value that cannot be normalized is reported by model, id and field
and left as stored; values are never printed (they are personal data).

  python manage.py normalize_contact_fields --dry-run   # counts only
  python manage.py normalize_contact_fields --apply     # write; safe to re-run

--apply writes with simple-history's bulk_update_with_history: each changed
row gets a history record, and no model save() runs (BillableContact.save
would also re-assign primaries, which is not this command's business).
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from rest_framework import serializers
from simple_history.utils import bulk_update_with_history

from billing.models import BillableContact, School, User
from billing.serializers import normalize_postal_code, phone_digits

TARGETS = (
    (User, ('phone_number', 'postal_code')),
    (BillableContact, ('phone', 'postal_code')),
    (School, ('phone_number', 'postal_code')),
)


def _canonical(field, value):
    """The canonical value, or None when it cannot be normalized."""
    if 'phone' in field:
        return phone_digits(value)
    try:
        return normalize_postal_code(value)
    except serializers.ValidationError:
        return None


class Command(BaseCommand):
    help = 'Normalize stored phones and postal codes on User, BillableContact and School'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--dry-run', action='store_true', help='Print counts; write nothing')
        mode.add_argument('--apply', action='store_true', help='Write the canonical values')

    def handle(self, *args, **options):
        apply = options['apply']
        self.stdout.write('APPLIED' if apply else 'DRY RUN (nothing written)')
        with transaction.atomic():
            for model, fields in TARGETS:
                self._normalize_model(model, fields, apply)

    def _normalize_model(self, model, fields, apply):
        counts = {field: {'change': 0, 'canonical': 0, 'blank': 0, 'skipped': 0} for field in fields}
        skipped = []
        rows = []
        for obj in model.objects.order_by('pk').iterator():
            changed = []
            for field in fields:
                outcome = self._classify(obj, field, apply)
                counts[field][outcome] += 1
                if outcome == 'change':
                    changed.append(field)
                elif outcome == 'skipped':
                    skipped.append(f'skipped {model.__name__} id={obj.pk} {field}')
            if changed:
                rows.append(obj)
        if apply and rows:
            bulk_update_with_history(
                rows, model, list(fields),
                default_change_reason='normalize_contact_fields (MAP-293)',
            )
        for field, c in counts.items():
            self.stdout.write(
                f"{model.__name__}.{field}: {c['change']} to change, {c['canonical']} canonical, "
                f"{c['blank']} blank, {c['skipped']} skipped"
            )
        for line in skipped:
            self.stdout.write(line)

    @staticmethod
    def _classify(obj, field, apply):
        value = getattr(obj, field) or ''
        if not value.strip():
            return 'blank'
        canonical = _canonical(field, value)
        if canonical is None:
            return 'skipped'
        if canonical == value:
            return 'canonical'
        if apply:
            setattr(obj, field, canonical)
        return 'change'
