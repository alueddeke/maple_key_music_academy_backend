"""
Unit tests for HelcimWebhookEvent model (HELM-04 — idempotency via unique constraint).

Covers:
- Creating with and without school (nullable school FK — Pitfall 2)
- unique constraint on helcim_transaction_id (IntegrityError on duplicate)
- get_or_create idempotency pattern (Plan 03 contract)
- __str__ format
- default amount is Decimal('0.00')
- invoice_id blank allowed
- school FK can be set after initial save (Phase 20 contract)
"""

import pytest
from decimal import Decimal
from django.db import IntegrityError

from billing.models import HelcimWebhookEvent


@pytest.mark.django_db
class TestHelcimWebhookEventModel:

    def test_create_helcim_webhook_event_with_school(self, school):
        """Creates a HelcimWebhookEvent with school FK populated."""
        event = HelcimWebhookEvent.objects.create(
            school=school,
            helcim_transaction_id='tx-001',
            raw_payload={'id': 'tx-001', 'type': 'cardTransaction'},
            amount=Decimal('60.00'),
        )
        assert event.pk is not None
        assert event.school == school
        assert event.helcim_transaction_id == 'tx-001'
        assert event.amount == Decimal('60.00')
        assert event.received_at is not None

    def test_create_helcim_webhook_event_without_school(self):
        """HelcimWebhookEvent saves with school=None (Pitfall 2 contract).

        Webhook receipt is unauthenticated — no school context available.
        Phase 20 sets school when the invoice resolves.
        """
        event = HelcimWebhookEvent.objects.create(
            school=None,
            helcim_transaction_id='tx-no-school',
            raw_payload={'id': 'tx-no-school', 'type': 'cardTransaction'},
        )
        assert event.pk is not None
        assert event.school is None

    def test_helcim_transaction_id_unique(self, school):
        """Creating a second event with same helcim_transaction_id raises IntegrityError (HELM-04)."""
        HelcimWebhookEvent.objects.create(
            school=school,
            helcim_transaction_id='tx-002',
            raw_payload={'id': 'tx-002'},
        )
        with pytest.raises(IntegrityError):
            HelcimWebhookEvent.objects.create(
                school=school,
                helcim_transaction_id='tx-002',
                raw_payload={'id': 'tx-002-duplicate'},
            )

    def test_get_or_create_returns_created_false_for_duplicate(self, school):
        """Plan 03 idempotency guard: second get_or_create returns created=False.

        Simulates Plan 03's pattern:
          event, created = HelcimWebhookEvent.objects.get_or_create(
              helcim_transaction_id=tx_id, defaults={...}
          )
        Second call must return the same object with created=False.
        """
        defaults = {
            'raw_payload': {'id': 'tx-003'},
            'invoice_id': 'INV-001',
            'amount': Decimal('75.00'),
        }
        event1, created1 = HelcimWebhookEvent.objects.get_or_create(
            helcim_transaction_id='tx-003',
            defaults=defaults,
        )
        assert created1 is True

        event2, created2 = HelcimWebhookEvent.objects.get_or_create(
            helcim_transaction_id='tx-003',
            defaults=defaults,
        )
        assert created2 is False
        assert event1.pk == event2.pk

    def test_str_format(self, school):
        """__str__ returns 'HelcimWebhookEvent #{tx_id} — {received_at}'."""
        event = HelcimWebhookEvent.objects.create(
            school=school,
            helcim_transaction_id='tx-str-test',
            raw_payload={'id': 'tx-str-test'},
        )
        expected = f"HelcimWebhookEvent #tx-str-test — {event.received_at}"
        assert str(event) == expected

    def test_default_amount_is_zero(self):
        """A newly-created event with no amount kwarg has amount == Decimal('0.00')."""
        event = HelcimWebhookEvent.objects.create(
            helcim_transaction_id='tx-default-amt',
            raw_payload={'id': 'tx-default-amt'},
        )
        assert event.amount == Decimal('0.00')

    def test_invoice_id_blank_allowed(self):
        """invoice_id='' saves successfully — Plan 03 may store blank until secondary GET."""
        event = HelcimWebhookEvent.objects.create(
            helcim_transaction_id='tx-blank-invoice',
            raw_payload={'id': 'tx-blank-invoice'},
            invoice_id='',
        )
        assert event.invoice_id == ''
        event.refresh_from_db()
        assert event.invoice_id == ''

    def test_school_set_later_works(self, school):
        """Phase 20 contract: school=None at receipt, set after invoice resolves."""
        event = HelcimWebhookEvent.objects.create(
            school=None,
            helcim_transaction_id='tx-phase20',
            raw_payload={'id': 'tx-phase20'},
        )
        assert event.school is None

        event.school = school
        event.save()

        event.refresh_from_db()
        assert event.school == school
        assert event.school.pk == school.pk
