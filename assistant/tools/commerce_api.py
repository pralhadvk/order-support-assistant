"""Mock commerce backend standing in for the real order service.

Behaves like an authenticated API: every call carries the caller's customer_id (from the session,
never from the LLM), and orders owned by someone else are indistinguishable from orders that don't
exist. SLA dates are derived here, as a real backend would, from the same windows the policy docs state.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assistant.config import settings

AUTO_REVERSAL_HOURS = 48  # DOC-2
REFUND_BUSINESS_DAYS = 7  # DOC-1 (upper bound)
INTERNATIONAL_EXTRA_BUSINESS_DAYS = 3  # DOC-6 (upper bound)
RETURN_RESOLUTION_BUSINESS_DAYS = 8
DISPUTE_RESOLUTION_BUSINESS_DAYS = 10  # DOC-3 (upper bound)

RETURNABLE_STATUSES = {"DELIVERED"}


class CommerceAPIError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}}


def add_business_days(start: datetime, days: int) -> datetime:
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _case_id(prefix: str, order_id: str) -> str:
    return f"{prefix}-{int(hashlib.sha256(order_id.encode()).hexdigest(), 16) % 100000:05d}"


class MockCommerceAPI:
    def __init__(self, orders_path: Path | None = None, now: datetime | None = None):
        path = orders_path or settings.data_dir / "mock_orders.json"
        self._orders = {o["order_id"]: o for o in json.loads(path.read_text())}
        self._now = now or settings.now
        self._cases: dict[tuple[str, str], dict] = {}  # (kind, order_id) -> case, for idempotency

    def _get_owned(self, order_id: str, customer_id: str) -> dict:
        order = self._orders.get(order_id.upper())
        if order is None or order["customer_id"] != customer_id:
            raise CommerceAPIError("ORDER_NOT_FOUND", f"No order {order_id} found for this account.")
        if order.get("_simulate_error") == "UPSTREAM_TIMEOUT":
            raise CommerceAPIError("UPSTREAM_TIMEOUT", "Order service did not respond in time.", retryable=True)
        return order

    def _sla_deadline(self, order: dict) -> datetime | None:
        placed = _parse(order["timestamp"])
        if order["status"] == "PAYMENT_FAILED":
            return placed + timedelta(hours=AUTO_REVERSAL_HOURS)
        if order["status"] == "RETURN_RECEIVED":
            extra = INTERNATIONAL_EXTRA_BUSINESS_DAYS if order.get("is_international") else 0
            return add_business_days(placed, REFUND_BUSINESS_DAYS + extra)
        return None

    def check_order_status(self, order_id: str, *, customer_id: str) -> dict:
        order = self._get_owned(order_id, customer_id)
        result = {
            "order_id": order["order_id"],
            "status": order["status"],
            "amount": order["amount"],
            "timestamp": order["timestamp"],
        }
        deadline = self._sla_deadline(order)
        if order["status"] == "PAYMENT_FAILED":
            result["failure_reason"] = order["failure_reason"]
            result["auto_reversal_expected_by"] = _fmt(deadline)
        elif order["status"] == "RETURN_RECEIVED":
            result["is_international"] = order.get("is_international", False)
            result["refund_expected_by"] = _fmt(deadline)
        if deadline is not None:
            result["sla_breached"] = self._now > deadline
        for kind in ("RETURN", "DISPUTE"):
            if (kind, order["order_id"]) in self._cases:
                result[f"open_{kind.lower()}_case"] = self._cases[(kind, order["order_id"])]["case_id"]
        return result

    def initiate_return(self, order_id: str, reason: str, *, customer_id: str, dry_run: bool = False) -> dict:
        """dry_run validates eligibility without creating a case (used before asking the customer to confirm)."""
        order = self._get_owned(order_id, customer_id)
        if not reason or not reason.strip():
            raise CommerceAPIError("INVALID_REQUEST", "A return reason is required.")
        key = ("RETURN", order["order_id"])
        if key in self._cases:
            return self._cases[key]
        if order["status"] not in RETURNABLE_STATUSES:
            raise CommerceAPIError(
                "NOT_ELIGIBLE", f"Order in status {order['status']} cannot be returned; only delivered orders can."
            )
        if dry_run:
            return {"eligible": True}
        case = {
            "case_id": _case_id("CASE", order["order_id"]),
            "status": "INITIATED",
            "expected_resolution_by": _fmt(add_business_days(self._now, RETURN_RESOLUTION_BUSINESS_DAYS)),
        }
        self._cases[key] = case
        return case

    def raise_dispute(self, order_id: str, reason: str, *, customer_id: str, dry_run: bool = False) -> dict:
        order = self._get_owned(order_id, customer_id)
        key = ("DISPUTE", order["order_id"])
        if key in self._cases:
            return self._cases[key]
        deadline = self._sla_deadline(order)
        if deadline is None:
            raise CommerceAPIError(
                "NOT_ELIGIBLE", f"Order in status {order['status']} has no pending refund or reversal to dispute."
            )
        if self._now <= deadline:
            raise CommerceAPIError(
                "NOT_ELIGIBLE", f"The standard window has not elapsed yet; it ends {_fmt(deadline)}."
            )
        if dry_run:
            return {"eligible": True}
        case = {
            "case_id": _case_id("DSP", order["order_id"]),
            "status": "DISPUTE_RAISED",
            "expected_resolution_by": _fmt(add_business_days(self._now, DISPUTE_RESOLUTION_BUSINESS_DAYS)),
        }
        self._cases[key] = case
        return case
