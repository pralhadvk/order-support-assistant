"""Policy gate tests. No LLM involved: these call the executor the way the model's tool calls would."""

import pytest

from assistant.order_ids import mentioned_order_ids
from assistant.session import Session, TurnTrace
from assistant.tools.commerce_api import MockCommerceAPI
from assistant.tools.executor import ToolExecutor


class NoSearch:
    def search(self, *a, **k):
        raise AssertionError("search not expected in this test")


def make(*customer_messages):
    session = Session()
    session.customer_messages.extend(customer_messages)
    return session, ToolExecutor(MockCommerceAPI(), NoSearch(), session, TurnTrace(session.session_id, session.turn, ""))


def code(result):
    return result.get("error", {}).get("code")


def say(session, executor, text):
    session.customer_messages.append(text)
    executor.trace = TurnTrace(session.session_id, session.turn, text)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("How long will my refund take for order ORD-7701?", {"ORD-7701"}),
        ("it's been 9 days for order #4521", {"ORD-4521"}),
        ("order 4521 and ord3300", {"ORD-4521", "ORD-3300"}),
        ("My order of Rs 5000 failed 3 days ago", set()),
        ("I paid ₹2500 on 22/09", set()),
    ],
)
def test_order_id_extraction_is_strict(text, expected):
    assert mentioned_order_ids([text]) == expected


def test_amount_is_never_used_as_order_id():
    _, ex = make("My order of Rs 5000 failed 3 days ago and I want a chargeback")
    assert code(ex.execute("check_order_status", {"order_id": "ORD-5000"})) == "ORDER_ID_NOT_FROM_CUSTOMER"


def test_other_customers_order_is_not_found():
    _, ex = make("check ORD-9999")
    assert code(ex.execute("check_order_status", {"order_id": "ORD-9999"})) == "ORDER_NOT_FOUND"


def test_timeout_is_retried_then_surfaced():
    session, ex = make("status of ORD-1313?")
    result = ex.execute("check_order_status", {"order_id": "ORD-1313"})
    assert code(result) == "UPSTREAM_TIMEOUT" and session.tool_failures == 1


def test_circuit_breaker_stops_calls_after_a_failed_call():
    session, ex = make("status of ORD-1313?")
    assert code(ex.execute("check_order_status", {"order_id": "ORD-1313"})) == "UPSTREAM_TIMEOUT"  # after one retry
    assert code(ex.execute("check_order_status", {"order_id": "ORD-1313"})) == "SERVICE_UNAVAILABLE"
    assert session.tool_failures == 1


def test_unknown_tool_is_rejected():
    _, ex = make("reset my password")
    assert code(ex.execute("reset_password", {})) == "UNKNOWN_TOOL"


def test_write_requires_status_check_first():
    _, ex = make("return ORD-3300, wrong size")
    assert code(ex.execute("initiate_return", {"order_id": "ORD-3300", "reason": "wrong size"})) == "CHECK_STATUS_FIRST"


def test_ineligible_write_fails_before_asking_for_confirmation():
    session, ex = make("dispute ORD-2210")
    ex.execute("check_order_status", {"order_id": "ORD-2210"})
    assert code(ex.execute("raise_dispute", {"order_id": "ORD-2210", "reason": "not reversed"})) == "NOT_ELIGIBLE"
    assert session.pending_action is None


def test_write_needs_confirmation_in_a_later_turn():
    session, ex = make("My payment for ORD-5000 failed and I don't have my money back")
    ex.execute("check_order_status", {"order_id": "ORD-5000"})
    args = {"order_id": "ORD-5000", "reason": "auto-reversal not received"}

    first = ex.execute("raise_dispute", args)
    assert first["status"] == "CONFIRMATION_REQUIRED"
    assert ex.execute("raise_dispute", args)["status"] == "CONFIRMATION_REQUIRED"  # same turn: still not executed

    say(session, ex, "yes please go ahead")
    done = ex.execute("raise_dispute", args)
    assert done["status"] == "DISPUTE_RAISED" and session.pending_action is None


def test_negative_reply_does_not_confirm():
    session, ex = make("return ORD-3300, it's the wrong size")
    ex.execute("check_order_status", {"order_id": "ORD-3300"})
    args = {"order_id": "ORD-3300", "reason": "wrong size"}
    ex.execute("initiate_return", args)
    say(session, ex, "no, wait, don't do that yet")
    assert ex.execute("initiate_return", args)["status"] == "CONFIRMATION_REQUIRED"


def test_locked_session_blocks_writes():
    session, ex = make("return ORD-3300")
    ex.execute("check_order_status", {"order_id": "ORD-3300"})
    session.write_tools_locked = True
    assert code(ex.execute("initiate_return", {"order_id": "ORD-3300", "reason": "x"})) == "ACTIONS_DISABLED"
