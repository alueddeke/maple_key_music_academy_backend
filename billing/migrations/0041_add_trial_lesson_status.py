# Stub migration — reconciles main branch's 0041 with develop's migration chain.
# The trial lesson status was added by main's 0041 on production.
# On develop this is handled by migration 0048 (plan 07-03). No operations here.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0040_batchlessonitem_admin_notes_main"),
    ]

    operations = []
