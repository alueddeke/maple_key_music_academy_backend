from django.apps import AppConfig

# Loads configuration for the billing app when project is run
class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "billing"

    def ready(self):
        # Import signals to register them
        import billing.signals
