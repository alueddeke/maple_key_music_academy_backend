# Stub migration — reconciles main branch's 0040 with develop's migration chain.
# The admin_notes column was added by main's 0040 on production.
# On develop the column is handled by 0047 (IF NOT EXISTS). No operations here.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0039_historicalmonthlyinvoicebatch_payment_date_and_more"),
    ]

    operations = []
