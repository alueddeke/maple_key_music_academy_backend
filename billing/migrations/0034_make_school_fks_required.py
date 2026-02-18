# Generated manually for Phase 3 - Multi-tenancy migration
# Migration 0034: Make school ForeignKeys required (NOT NULL)

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0033_backfill_invoicerecipientemail_school'),
    ]

    operations = [
        # User.school: Make required
        migrations.AlterField(
            model_name='user',
            name='school',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='users',
                to='billing.school',
                help_text='School this user belongs to'
            ),
        ),
        # BillableContact.school: Make required
        migrations.AlterField(
            model_name='billablecontact',
            name='school',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='billable_contacts',
                to='billing.school',
                help_text='School this billable contact belongs to'
            ),
        ),
        # Lesson.school: Make required
        migrations.AlterField(
            model_name='lesson',
            name='school',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='lessons',
                to='billing.school',
                help_text='School this lesson belongs to'
            ),
        ),
        # Invoice.school: Make required
        migrations.AlterField(
            model_name='invoice',
            name='school',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='invoices',
                to='billing.school',
                help_text='School this invoice belongs to'
            ),
        ),
        # InvoiceRecipientEmail.school: Make required
        migrations.AlterField(
            model_name='invoicerecipientemail',
            name='school',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='invoice_recipient_emails',
                to='billing.school',
                help_text='School this invoice recipient belongs to'
            ),
        ),
    ]
