"""Pluggable SMS delivery interface.

No SMS vendor has been chosen yet (needs a product decision) — the default
provider is a logging no-op. To wire a real vendor later, implement
SMSProvider and return it from get_sms_provider(); nothing else changes.
"""

import logging

logger = logging.getLogger(__name__)


class SMSProvider:
    """Interface for SMS delivery providers."""

    def send(self, phone_number: str, message: str) -> bool:
        """Send an SMS. Returns True if the provider accepted the message."""
        raise NotImplementedError


class NoOpSMSProvider(SMSProvider):
    """Stub provider — logs instead of sending. Used until a vendor is chosen."""

    def send(self, phone_number: str, message: str) -> bool:
        logger.info(
            "SMS delivery stubbed (no provider configured): to=%s message=%r",
            phone_number,
            message[:100],
        )
        return False


def get_sms_provider() -> SMSProvider:
    """Return the active SMS provider.

    NEEDS-PROVIDER-DECISION: swap NoOpSMSProvider for a real implementation
    (e.g. Twilio) once a vendor is chosen. Keep the interface unchanged.
    """
    return NoOpSMSProvider()
