from django.apps import AppConfig

#loads configuration for the billing app when project is run
class Test1Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "billing"

    def ready(self):
        # Import signals to register them
        import billing.signals
