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


def helcim_subdomain_for(school=None):
    """
    Resolve the Helcim account subdomain used to build hosted-payment URLs.

    Per-school credentials (School.helcim_subdomain) win when set; blank falls
    back to the HELCIM_SUBDOMAIN env setting (the first/default school).
    Duck-typed: accepts any object with a helcim_subdomain attribute (D-01 —
    no model imports in this module).
    """
    if school is not None and getattr(school, 'helcim_subdomain', ''):
        return school.helcim_subdomain
    return settings.HELCIM_SUBDOMAIN


def payment_page_url(token, school=None):
    """Build the hosted-payment URL for a Helcim invoice payment token."""
    return f"https://{helcim_subdomain_for(school)}.myhelcim.com/order/?token={token}"


class HelcimClient:
    """
    Thin HTTP client for the Helcim v2 REST API.

    Credentials resolve per school when the School has its own Helcim fields
    set (multi-school); blank school fields fall back to Django settings.
    Settings.HELCIM_API_TOKEN and settings.HELCIM_TERMINAL_ID are validated
    at startup by billing/apps.py:BillingConfig.ready() (Plan 02).

    Usage:
        client = HelcimClient(school=invoice.school)
        invoice = client.create_invoice('CAD', [{'description': 'Lesson', 'quantity': 1.0, 'price': 60.00}])
    """

    def __init__(self, school=None):
        # Duck-typed school (D-01: no model imports). None → env settings.
        if school is not None and getattr(school, 'helcim_api_token', ''):
            self.api_token = school.helcim_api_token
            self.terminal_id = school.helcim_terminal_id or settings.HELCIM_TERMINAL_ID
        else:
            self.api_token = settings.HELCIM_API_TOKEN
            self.terminal_id = settings.HELCIM_TERMINAL_ID  # stored but NOT sent in invoice request body

    def _headers(self):
        """Return standard Helcim API request headers."""
        return {
            'api-token': self.api_token,
            'Content-Type': 'application/json',
        }

    def create_invoice(self, currency, line_items, customer_id=None, discount=None):
        """
        POST /v2/invoices

        Args:
            currency: ISO 4217 currency code, e.g. 'CAD'
            line_items: list of dicts with keys 'description', 'quantity', 'price'
            customer_id: optional Helcim customer ID integer
            discount: optional dict {'amount': float, 'details': str} — Helcim
                subtracts it from the invoice total (amountDue = lineItems − discount).
                Line-item prices must be non-negative; a negative "credit" line
                item is rejected by the API, so credit rides here instead.

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
        if discount is not None:
            payload['discount'] = discount

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

    def create_customer(self, contact_name, billing_address=None):
        """
        POST /v2/customers/

        Args:
            contact_name: billing contact full name (str)
            billing_address: optional dict with Helcim billing address fields

        Returns:
            dict — caller reads response['id'] (integer Helcim customer ID).
            Per Helcim devdocs the primary key field on a customer resource is 'id'.

        Raises:
            HelcimAPIError: on non-2xx response or timeout
        """
        payload = {'contactName': contact_name}
        if billing_address is not None:
            payload['billingAddress'] = billing_address

        try:
            response = requests.post(
                f'{HELCIM_API_BASE}/customers/',
                json=payload,
                headers=self._headers(),
                timeout=HELCIM_TIMEOUT,
            )
        except requests.Timeout:
            logger.error('Helcim %s timeout after %ds', 'create_customer', HELCIM_TIMEOUT)
            raise HelcimAPIError('Helcim create_customer timeout', status_code=None)

        if not response.ok:
            logger.error(
                'Helcim %s failed: status=%s body=%s',
                'create_customer',
                response.status_code,
                response.text,
            )
            raise HelcimAPIError(
                f'Helcim create_customer failed: {response.status_code}',
                status_code=response.status_code,
                raw_response=response.text,
            )

        return response.json()

    def cancel_invoice(self, invoice_id, currency='CAD', line_items=None):
        """
        PUT /v2/invoices/{invoiceId}

        Sets invoice status to CANCELLED.
        Per RESEARCH.md: PUT (not PATCH) is the verified HTTP method.

        The Helcim OpenAPI schema for PUT /v2/invoices/{invoiceId} lists `currency`
        and `lineItems` as required fields (Pitfall 7 / Assumption A1 in 19-RESEARCH.md).
        This method accepts them defensively: if Helcim requires them even for
        cancellation, pass the original invoice's currency and line items.
        If the sandbox later confirms that `{'status': 'CANCELLED'}` alone works,
        the extra fields are harmless and can be dropped.

        Args:
            invoice_id: Helcim invoice ID string
            currency:   ISO 4217 currency code, default 'CAD'
            line_items: list of dicts with keys 'description', 'quantity', 'price';
                        if None, only status is sent (may be rejected by Helcim)

        Returns:
            dict with updated invoice fields

        Raises:
            HelcimAPIError: on non-2xx response or timeout
        """
        payload = {'status': 'CANCELLED', 'currency': currency}
        if line_items is not None:
            payload['lineItems'] = line_items

        try:
            response = requests.put(
                f'{HELCIM_API_BASE}/invoices/{invoice_id}',
                json=payload,
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

    def list_card_transactions(self, limit=50):
        """
        GET /v2/card-transactions?limit={limit}

        Used by sync_helcim_payments to reconcile payments whose webhooks
        never arrived (endpoint down longer than Helcim's ~10h retry window,
        or dev tunnel offline). Returns the raw list of transaction dicts.

        Raises:
            HelcimAPIError: on non-2xx response or timeout
        """
        try:
            response = requests.get(
                f'{HELCIM_API_BASE}/card-transactions',
                params={'limit': limit},
                headers=self._headers(),
                timeout=HELCIM_TIMEOUT,
            )
        except requests.Timeout:
            logger.error('Helcim %s timeout after %ds', 'list_card_transactions', HELCIM_TIMEOUT)
            raise HelcimAPIError('Helcim list_card_transactions timeout', status_code=None)

        if not response.ok:
            logger.error(
                'Helcim %s failed: status=%s body=%s',
                'list_card_transactions',
                response.status_code,
                response.text,
            )
            raise HelcimAPIError(
                f'Helcim list_card_transactions failed: {response.status_code}',
                status_code=response.status_code,
                raw_response=response.text,
            )

        data = response.json()
        # Helcim returns either a bare list or an object wrapping one.
        return data if isinstance(data, list) else data.get('data', [])

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
