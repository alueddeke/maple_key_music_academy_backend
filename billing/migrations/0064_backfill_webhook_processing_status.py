"""
Backfill processing_status for HelcimWebhookEvent rows created before the
gating/retry fields existed (migration 0063).

Old webhook handler behavior: school was set only after a credit was
successfully applied, so:
  - school IS NOT NULL           → credit applied      → 'credited'
  - school IS NULL, no invoice_id → secondary GET failed → 'enrichment_failed' (retryable)
  - school IS NULL, invoice_id    → no invoice matched   → 'no_invoice' (retryable)
"""

from django.db import migrations


def backfill(apps, schema_editor):
    HelcimWebhookEvent = apps.get_model('billing', 'HelcimWebhookEvent')
    HelcimWebhookEvent.objects.filter(school__isnull=False).update(
        processing_status='credited'
    )
    HelcimWebhookEvent.objects.filter(school__isnull=True, invoice_id='').update(
        processing_status='enrichment_failed'
    )
    HelcimWebhookEvent.objects.filter(school__isnull=True).exclude(invoice_id='').update(
        processing_status='no_invoice'
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0063_helcimwebhookevent_last_error_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
