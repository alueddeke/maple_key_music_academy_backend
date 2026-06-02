"""
HelcimClient — HTTP service class for Helcim REST API calls.

D-01: No Django model imports — pure HTTP service; unit-testable without ORM.
D-02: All failure paths raise HelcimAPIError (no silent failures).
D-03: All requests use a 10-second timeout; requests.Timeout → HelcimAPIError.
D-04: HelcimAPIError defined in this same file.
D-07: PCI scope — caller responsible for storing only helcim_invoice_id /
       helcim_transaction_id / helcim_customer_id. This file returns raw dicts.
"""

import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

HELCIM_API_BASE = 'https://api.helcim.com/v2'
HELCIM_TIMEOUT = 10  # seconds — matches Google OAuth 10-second pattern (D-03)


class HelcimAPIError(Exception):
    """Raised for any Helcim API failure: non-2xx response, timeout, or network error."""

    def __init__(self, message, status_code=None, raw_response=None):
        super().__init__(message)
        self.status_code = status_code
        self.raw_response = raw_response


class HelcimClient:
    """
    Thin HTTP client for the Helcim v2 REST API.

    Credentials are read from Django settings at instantiation time.
    Settings.HELCIM_API_TOKEN and settings.HELCIM_TERMINAL_ID are validated
    at startup by billing/apps.py:BillingConfig.ready() (Plan 02).

    Usage:
        client = HelcimClient()
        invoice = client.create_invoice('CAD', [{'description': 'Lesson', 'quantity': 1.0, 'price': 60.00}])
    """

    def __init__(self):
        # Credentials loaded at instantiation — settings validated at startup in apps.py:ready()
        self.api_token = settings.HELCIM_API_TOKEN
        self.terminal_id = settings.HELCIM_TERMINAL_ID  # stored but NOT sent in invoice request body

    def _headers(self):
        """Return standard Helcim API request headers."""
        return {
            'api-token': self.api_token,
            'Content-Type': 'application/json',
        }

    def create_invoice(self, currency, line_items, customer_id=None):
        """
        POST /v2/invoices

        Args:
            currency: ISO 4217 currency code, e.g. 'CAD'
            line_items: list of dicts with keys 'description', 'quantity', 'price'
            customer_id: optional Helcim customer ID integer

        Returns:
            dict with invoiceId, invoiceNumber, token (for hosted payment page), etc.

        Raises:
            HelcimAPIError: on non-2xx response or timeout
        """
        payload = {
            'currency': currency,
            'lineItems': line_items,
        }
        if customer_id is not None:
            payload['customerId'] = customer_id

        try:
            response = requests.post(
                f'{HELCIM_API_BASE}/invoices',
                json=payload,
                headers=self._headers(),
                timeout=HELCIM_TIMEOUT,
            )
        except requests.Timeout:
            logger.error('Helcim %s timeout after %ds', 'create_invoice', HELCIM_TIMEOUT)
            raise HelcimAPIError('Helcim create_invoice timeout', status_code=None)

        if not response.ok:
            logger.error(
                'Helcim %s failed: status=%s body=%s',
                'create_invoice',
                response.status_code,
                response.text,
            )
            raise HelcimAPIError(
                f'Helcim create_invoice failed: {response.status_code}',
                status_code=response.status_code,
                raw_response=response.text,
            )

        return response.json()

    def cancel_invoice(self, invoice_id):
        """
        PUT /v2/invoices/{invoiceId}

        Sets invoice status to CANCELLED.
        Per RESEARCH.md: PUT (not PATCH) is the verified HTTP method.

        Args:
            invoice_id: Helcim invoice ID string

        Returns:
            dict with updated invoice fields

        Raises:
            HelcimAPIError: on non-2xx response or timeout
        """
        try:
            response = requests.put(
                f'{HELCIM_API_BASE}/invoices/{invoice_id}',
                json={'status': 'CANCELLED'},
                headers=self._headers(),
                timeout=HELCIM_TIMEOUT,
            )
        except requests.Timeout:
            logger.error('Helcim %s timeout after %ds', 'cancel_invoice', HELCIM_TIMEOUT)
            raise HelcimAPIError('Helcim cancel_invoice timeout', status_code=None)

        if not response.ok:
            logger.error(
                'Helcim %s failed: status=%s body=%s',
                'cancel_invoice',
                response.status_code,
                response.text,
            )
            raise HelcimAPIError(
                f'Helcim cancel_invoice failed: {response.status_code}',
                status_code=response.status_code,
                raw_response=response.text,
            )

        return response.json()

    def get_card_transaction(self, transaction_id):
        """
        GET /v2/card-transactions/{transactionId}

        Used by the webhook handler (Plan 03) to retrieve invoiceNumber after
        receiving a minimal webhook payload (which contains only id + type).
        Per D-13 resolution: secondary GET is required; invoiceNumber is in
        the card transaction response, not in the webhook payload.

        Args:
            transaction_id: Helcim card transaction ID string

        Returns:
            dict with id, invoiceNumber, amount, and other transaction fields

        Raises:
            HelcimAPIError: on non-2xx response or timeout
        """
        try:
            response = requests.get(
                f'{HELCIM_API_BASE}/card-transactions/{transaction_id}',
                headers=self._headers(),
                timeout=HELCIM_TIMEOUT,
            )
        except requests.Timeout:
            logger.error('Helcim %s timeout after %ds', 'get_card_transaction', HELCIM_TIMEOUT)
            raise HelcimAPIError('Helcim get_card_transaction timeout', status_code=None)

        if not response.ok:
            logger.error(
                'Helcim %s failed: status=%s body=%s',
                'get_card_transaction',
                response.status_code,
                response.text,
            )
            raise HelcimAPIError(
                f'Helcim get_card_transaction failed: {response.status_code}',
                status_code=response.status_code,
                raw_response=response.text,
            )

        return response.json()
