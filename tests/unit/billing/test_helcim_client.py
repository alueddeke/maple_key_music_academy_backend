"""
Unit tests for billing.services.helcim_client.

Covers:
  - HelcimClient.create_invoice(): happy path, with customer_id, non-2xx error, timeout
  - HelcimClient.cancel_invoice(): happy path, non-2xx error, timeout
  - HelcimClient.get_card_transaction(): happy path, non-2xx error, timeout
  - HelcimAPIError attributes: status_code, raw_response, str()
  - D-01 regression guard: no billing.models imports in helcim_client.py

Design follows D-06 testing principles (Phase 16 CONTEXT.md):
  1. Fail safely, fail fast, fail closed.
  2. 100% coverage of HelcimClient HTTP methods.
  3. Every method: 1 happy path + 1 failing path (contrast ensures accuracy).
  4. Test behaviour, not implementation.
  5. Ideal and non-ideal circumstances covered.
  6. No implicit defaults — all assertions explicit.

No @pytest.mark.django_db — HelcimClient has no model imports (D-01).
Tests run without DB fixture, so they run fast and in isolation.
"""

import os
import requests
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from billing.services.helcim_client import (
    HELCIM_API_BASE,
    HELCIM_TIMEOUT,
    HelcimAPIError,
    HelcimClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(ok=True, status_code=200, json_data=None, text=''):
    """Build a MagicMock that mimics a requests.Response."""
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
    return resp


def _make_client():
    """Instantiate HelcimClient with test credentials already set via conftest.py env defaults."""
    return HelcimClient()


# ---------------------------------------------------------------------------
# create_invoice tests
# ---------------------------------------------------------------------------

@patch('billing.services.helcim_client.requests.post')
def test_create_invoice_happy(mock_post):
    """create_invoice returns parsed JSON dict on 2xx; correct URL, body, headers, timeout."""
    invoice_data = {'invoiceId': 'INV-1', 'invoiceNumber': '001', 'token': 'tok123'}
    mock_post.return_value = _make_response(ok=True, status_code=200, json_data=invoice_data)

    line_items = [{'description': 'Lesson', 'quantity': 1.0, 'price': 60.00}]
    result = _make_client().create_invoice('CAD', line_items)

    assert result == invoice_data

    # Verify the POST was called once with the right arguments
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args

    # URL check
    assert call_kwargs[0][0] == f'{HELCIM_API_BASE}/invoices'

    # Body check — currency + lineItems only (no customerId, no terminalId)
    body = call_kwargs[1]['json']
    assert body['currency'] == 'CAD'
    assert body['lineItems'] == line_items
    assert 'customerId' not in body
    assert 'terminalId' not in body

    # Headers must include api-token
    headers = call_kwargs[1]['headers']
    assert 'api-token' in headers

    # Timeout must equal HELCIM_TIMEOUT
    assert call_kwargs[1]['timeout'] == HELCIM_TIMEOUT


@patch('billing.services.helcim_client.requests.post')
def test_create_invoice_with_customer_id(mock_post):
    """create_invoice includes customerId in body when customer_id argument is passed."""
    invoice_data = {'invoiceId': 'INV-2', 'invoiceNumber': '002', 'token': 'tok456'}
    mock_post.return_value = _make_response(ok=True, status_code=200, json_data=invoice_data)

    line_items = [{'description': 'Lesson', 'quantity': 1.0, 'price': 60.00}]
    result = _make_client().create_invoice('CAD', line_items, customer_id=42)

    assert result == invoice_data
    body = mock_post.call_args[1]['json']
    assert body['customerId'] == 42


@patch('billing.services.helcim_client.requests.post')
def test_create_invoice_non_2xx(mock_post):
    """create_invoice raises HelcimAPIError on non-2xx response with status_code + raw_response."""
    error_text = '{"error":"bad request"}'
    mock_post.return_value = _make_response(ok=False, status_code=400, text=error_text)

    with pytest.raises(HelcimAPIError) as exc_info:
        _make_client().create_invoice('CAD', [])

    exc = exc_info.value
    assert exc.status_code == 400
    assert exc.raw_response == error_text


@patch('billing.services.helcim_client.requests.post')
def test_create_invoice_timeout(mock_post):
    """create_invoice raises HelcimAPIError with status_code=None on requests.Timeout."""
    mock_post.side_effect = requests.Timeout

    with pytest.raises(HelcimAPIError) as exc_info:
        _make_client().create_invoice('CAD', [])

    assert exc_info.value.status_code is None


# ---------------------------------------------------------------------------
# cancel_invoice tests
# ---------------------------------------------------------------------------

@patch('billing.services.helcim_client.requests.put')
def test_cancel_invoice_happy(mock_put):
    """cancel_invoice returns parsed JSON; issues PUT with {'status': 'CANCELLED'} body."""
    cancelled_data = {'invoiceId': 'INV-1', 'status': 'CANCELLED'}
    mock_put.return_value = _make_response(ok=True, status_code=200, json_data=cancelled_data)

    result = _make_client().cancel_invoice('INV-1')

    assert result == cancelled_data

    # URL must include the invoice ID
    mock_put.assert_called_once()
    call_kwargs = mock_put.call_args
    assert call_kwargs[0][0] == f'{HELCIM_API_BASE}/invoices/INV-1'

    # Body must include status=CANCELLED (may also include currency and other fields)
    assert call_kwargs[1]['json']['status'] == 'CANCELLED'

    # Headers must include api-token
    assert 'api-token' in call_kwargs[1]['headers']


@patch('billing.services.helcim_client.requests.put')
def test_cancel_invoice_non_2xx(mock_put):
    """cancel_invoice raises HelcimAPIError on non-2xx response with status_code."""
    mock_put.return_value = _make_response(ok=False, status_code=404, text='{"error":"not found"}')

    with pytest.raises(HelcimAPIError) as exc_info:
        _make_client().cancel_invoice('INV-MISSING')

    assert exc_info.value.status_code == 404


@patch('billing.services.helcim_client.requests.put')
def test_cancel_invoice_timeout(mock_put):
    """cancel_invoice raises HelcimAPIError with status_code=None on requests.Timeout."""
    mock_put.side_effect = requests.Timeout

    with pytest.raises(HelcimAPIError) as exc_info:
        _make_client().cancel_invoice('INV-1')

    assert exc_info.value.status_code is None


# ---------------------------------------------------------------------------
# get_card_transaction tests
# ---------------------------------------------------------------------------

@patch('billing.services.helcim_client.requests.get')
def test_get_card_transaction_happy(mock_get):
    """get_card_transaction returns parsed JSON; issues GET to correct URL with api-token."""
    tx_data = {'id': '25764674', 'invoiceNumber': '001', 'amount': 60.00}
    mock_get.return_value = _make_response(ok=True, status_code=200, json_data=tx_data)

    result = _make_client().get_card_transaction('25764674')

    assert result == tx_data

    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args

    # URL must be the card-transactions endpoint with the transaction ID
    assert call_kwargs[0][0] == f'{HELCIM_API_BASE}/card-transactions/25764674'

    # Headers must include api-token
    assert 'api-token' in call_kwargs[1]['headers']


@patch('billing.services.helcim_client.requests.get')
def test_get_card_transaction_non_2xx(mock_get):
    """get_card_transaction raises HelcimAPIError on non-2xx with status_code."""
    mock_get.return_value = _make_response(ok=False, status_code=500, text='server error')

    with pytest.raises(HelcimAPIError) as exc_info:
        _make_client().get_card_transaction('25764674')

    assert exc_info.value.status_code == 500


@patch('billing.services.helcim_client.requests.get')
def test_get_card_transaction_timeout(mock_get):
    """get_card_transaction raises HelcimAPIError with status_code=None on requests.Timeout."""
    mock_get.side_effect = requests.Timeout

    with pytest.raises(HelcimAPIError) as exc_info:
        _make_client().get_card_transaction('25764674')

    assert exc_info.value.status_code is None


# ---------------------------------------------------------------------------
# HelcimAPIError attribute tests
# ---------------------------------------------------------------------------

def test_helcim_api_error_attributes():
    """HelcimAPIError stores status_code + raw_response; str() returns the message."""
    exc = HelcimAPIError('something failed', status_code=502, raw_response='boom')

    assert exc.status_code == 502
    assert exc.raw_response == 'boom'
    assert str(exc) == 'something failed'


# ---------------------------------------------------------------------------
# D-01 regression guard: no billing.models imports
# ---------------------------------------------------------------------------

def test_no_django_model_imports():
    """Regression guard: helcim_client.py must never import from billing.models (D-01).

    Reads the source file as text and asserts that no Django model import patterns
    appear. This test fails immediately if D-01 is ever violated, catching the
    architectural constraint early rather than at runtime.
    """
    import inspect
    import billing.services.helcim_client as helcim_module

    source = inspect.getsource(helcim_module)

    assert 'billing.models' not in source, (
        "D-01 violated: billing.models import found in helcim_client.py"
    )
    assert 'from ..models' not in source, (
        "D-01 violated: relative ..models import found in helcim_client.py"
    )
    assert 'from billing.models' not in source, (
        "D-01 violated: from billing.models import found in helcim_client.py"
    )
