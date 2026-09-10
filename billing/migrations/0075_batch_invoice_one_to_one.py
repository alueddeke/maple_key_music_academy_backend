# MAP-183: one payroll invoice per batch, enforced by the database.
#
# MonthlyInvoiceBatch.invoice becomes a OneToOneField (unique on invoice_id,
# on_delete=PROTECT). The unique index can only be created once no two batches
# point at the same invoice, so the data step runs first (D2, ratified
# 2026-09-10): for every invoice referenced by more than one batch, the batch
# with the lowest id keeps the pointer, the others are set to NULL and their
# ids are logged. Reverse restores the nullable ForeignKey(SET_NULL); the
# nulled pointers are not restored (data step is a no-op backwards).
#
# The simple-history shadow field (historicalmonthlyinvoicebatch.invoice) is
# stored as a plain ForeignKey(DO_NOTHING, db_constraint=False) for both field
# types, so it needs no alteration.

import logging

import django.db.models.deletion
from django.db import migrations, models

logger = logging.getLogger(__name__)


def null_duplicate_batch_pointers(apps, schema_editor):
    MonthlyInvoiceBatch = apps.get_model('billing', 'MonthlyInvoiceBatch')
    duplicates = (
        MonthlyInvoiceBatch.objects
        .filter(invoice_id__isnull=False)
        .values('invoice_id')
        .annotate(n=models.Count('id'))
        .filter(n__gt=1)
    )
    for row in duplicates:
        batches = MonthlyInvoiceBatch.objects.filter(
            invoice_id=row['invoice_id']
        ).order_by('id')
        keep = batches.first()
        losers = list(batches.exclude(id=keep.id).values_list('id', flat=True))
        MonthlyInvoiceBatch.objects.filter(id__in=losers).update(invoice=None)
        logger.warning(
            'MAP-183 migration 0075: invoice %s was linked from batches %s; '
            'kept batch %s, set invoice = NULL on batches %s',
            row['invoice_id'], [keep.id] + losers, keep.id, losers,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0074_ledger_sources_and_issued_items'),
    ]

    operations = [
        migrations.RunPython(null_duplicate_batch_pointers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='monthlyinvoicebatch',
            name='invoice',
            field=models.OneToOneField(blank=True, help_text='The teacher payment invoice created from this batch', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='source_batch', to='billing.invoice'),
        ),
    ]
