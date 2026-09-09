import os

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


# Loads configuration for the billing app when project is run
class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "billing"

    def ready(self):
        # Import signals to register them
        import billing.signals

        # HELM-02: Fail fast at startup if Helcim credentials are missing.
        # Reads via os.environ (not settings.*) because AppConfig.ready() runs before
        # django.conf.settings is guaranteed safe in some test paths.
        if not os.environ.get('HELCIM_API_TOKEN'):
            raise ImproperlyConfigured(
                "HELCIM_API_TOKEN environment variable is required but not set."
            )
        if not os.environ.get('HELCIM_TERMINAL_ID'):
            raise ImproperlyConfigured(
                "HELCIM_TERMINAL_ID environment variable is required but not set."
            )
        if not os.environ.get('HELCIM_WEBHOOK_SECRET'):
            raise ImproperlyConfigured(
                "HELCIM_WEBHOOK_SECRET environment variable is required but not set."
            )
        if not os.environ.get('HELCIM_SUBDOMAIN'):
            raise ImproperlyConfigured(
                "HELCIM_SUBDOMAIN environment variable is required but not set."
            )

        # MAP-181: a production process must never run with DEBUG on. No-op when
        # MAPLEKEY_ENV is unset (image build, CI, dev).
        if os.environ.get('MAPLEKEY_ENV') == 'prod' and os.environ.get('DEBUG', '').lower() == 'true':
            raise ImproperlyConfigured('DEBUG must be False when MAPLEKEY_ENV=prod')
