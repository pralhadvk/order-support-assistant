import pytest

from assistant.tools.commerce_api import CommerceAPIError, MockCommerceAPI

ME = "CUST-001"


@pytest.fixture
def api():
    return MockCommerceAPI()


def test_brief_example_payload(api):
    result = api.check_order_status("ORD-4521", customer_id=ME)
    assert result["status"] == "PAYMENT_FAILED"
    assert result["failure_reason"] == "GATEWAY_TIMEOUT"
    assert result["auto_reversal_expected_by"] == "2026-09-24T14:03:00Z"
    assert result["sla_breached"] is True


def test_recent_failed_payment_is_inside_window(api):
    assert api.check_order_status("ORD-2210", customer_id=ME)["sla_breached"] is False


def test_domestic_return_refund_window(api):
    result = api.check_order_status("ORD-7701", customer_id=ME)
    assert result["refund_expected_by"] == "2026-10-02T11:30:00Z"  # 7 business days after Wed 23 Sep
    assert result["sla_breached"] is False


def test_international_return_gets_extra_days(api):
    result = api.check_order_status("ORD-6100", customer_id=ME)
    assert result["refund_expected_by"] == "2026-09-30T08:00:00Z"  # 7 + 3 business days
    assert result["sla_breached"] is False


@pytest.mark.parametrize("order_id", ["ORD-9999", "ORD-0000"])
def test_other_customers_order_looks_like_missing(api, order_id):
    with pytest.raises(CommerceAPIError) as exc:
        api.check_order_status(order_id, customer_id=ME)
    assert exc.value.code == "ORDER_NOT_FOUND"


def test_upstream_timeout_is_retryable(api):
    with pytest.raises(CommerceAPIError) as exc:
        api.check_order_status("ORD-1313", customer_id=ME)
    assert exc.value.code == "UPSTREAM_TIMEOUT" and exc.value.retryable


def test_initiate_return_is_idempotent(api):
    first = api.initiate_return("ORD-3300", "wrong size", customer_id=ME)
    assert first["status"] == "INITIATED" and first["case_id"].startswith("CASE-")
    assert api.initiate_return("ORD-3300", "wrong size", customer_id=ME) == first
    assert api.check_order_status("ORD-3300", customer_id=ME)["open_return_case"] == first["case_id"]


def test_cannot_return_a_failed_payment(api):
    with pytest.raises(CommerceAPIError) as exc:
        api.initiate_return("ORD-4521", "want money back", customer_id=ME)
    assert exc.value.code == "NOT_ELIGIBLE"


def test_dispute_allowed_only_after_window(api):
    assert api.raise_dispute("ORD-5000", "not reversed", customer_id=ME)["status"] == "DISPUTE_RAISED"
    with pytest.raises(CommerceAPIError) as exc:
        api.raise_dispute("ORD-2210", "not reversed", customer_id=ME)
    assert exc.value.code == "NOT_ELIGIBLE"
