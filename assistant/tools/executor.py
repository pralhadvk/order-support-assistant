"""Executes tool calls proposed by the LLM, behind deterministic policy gates.

The model decides *what* it wants to do; this module decides whether it is allowed. Every rule that
protects money or customer data lives here rather than in the prompt, so a jailbroken or confused
model still cannot act outside them:

- order IDs must have been typed by the customer (no hallucinated or amount-derived IDs)
- customer_id always comes from the session (ownership is enforced by the API)
- write actions need: a prior status check, eligibility (dry run), and explicit confirmation from
  the customer in a later turn
- write actions are disabled when guardrails flag the conversation
- write actions on high-value orders are handed to a human instead of executing
- retryable upstream errors are retried once, then surfaced as structured errors
"""

import hashlib
import re
import time

from assistant.config import settings
from assistant.order_ids import mentioned_order_ids, normalize_order_id
from assistant.search import PolicySearch
from assistant.session import Session, TurnTrace
from assistant.tools.commerce_api import CommerceAPIError, MockCommerceAPI

WRITE_TOOLS = {"initiate_return", "raise_dispute"}
MAX_ATTEMPTS = 2
RETRY_BACKOFF_S = 0.2

_AFFIRM = re.compile(r"\b(yes|yeah|yep|sure|ok|okay|please do|go ahead|confirm(ed)?|do it|proceed|raise it)\b", re.I)
_NEGATE = re.compile(r"\b(no|not|don'?t|cancel|wait|stop)\b", re.I)


def is_affirmative(text: str) -> bool:
    return bool(_AFFIRM.search(text)) and not _NEGATE.search(text)


def gate_error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "source": "policy_gate"}}


class ToolExecutor:
    def __init__(self, api: MockCommerceAPI, search: PolicySearch, session: Session, trace: TurnTrace):
        self.api = api
        self.search = search
        self.session = session
        self.trace = trace
        self._handlers = {
            "search_policy": self.search_policy,
            "check_order_status": self.check_order_status,
            "initiate_return": lambda order_id, reason: self._write_action("initiate_return", order_id, reason),
            "raise_dispute": lambda order_id, reason: self._write_action("raise_dispute", order_id, reason),
            "escalate_to_human": self.escalate_to_human,
        }

    def execute(self, name: str, args: dict) -> dict:
        start = time.perf_counter()
        handler = self._handlers.get(name)
        if handler is None:
            result = gate_error("UNKNOWN_TOOL", f"There is no tool named '{name}'. Do not improvise capabilities.")
        else:
            try:
                result = handler(**args)
            except TypeError as exc:
                result = gate_error("INVALID_ARGUMENTS", str(exc))
        self.trace.tool_calls.append(
            {"tool": name, "args": args, "result": result, "ms": round((time.perf_counter() - start) * 1000, 1)}
        )
        return result

    # --- order ID gate -------------------------------------------------------------------------

    def _resolve_order_id(self, raw: str) -> tuple[str | None, dict | None]:
        order_id = normalize_order_id(raw or "")
        if order_id is None:
            return None, gate_error("INVALID_ORDER_ID", f"'{raw}' is not a valid order ID (expected e.g. ORD-4521).")
        if order_id not in mentioned_order_ids(self.session.customer_messages):
            return None, gate_error(
                "ORDER_ID_NOT_FROM_CUSTOMER",
                f"The customer has not provided order ID {order_id}. Ask them for their order ID; never guess one.",
            )
        return order_id, None

    def _call_api(self, fn, *args, **kwargs) -> dict:
        # Circuit breaker: stop the model from hammering a failing upstream with repeated calls.
        if self.session.tool_failures >= settings.max_tool_failures:
            return gate_error(
                "SERVICE_UNAVAILABLE",
                "The order service has failed repeatedly in this conversation. Do not retry; tell the customer and "
                "offer a human agent.",
            )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return fn(*args, customer_id=self.session.customer_id, **kwargs)
            except CommerceAPIError as exc:
                if exc.retryable and attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_S * attempt)
                    continue
                if exc.retryable:
                    self.session.tool_failures += 1
                return exc.to_dict()

    # --- tools ---------------------------------------------------------------------------------

    def search_policy(self, query: str, order_id: str | None = None) -> dict:
        status = None
        if order_id:
            normalised = normalize_order_id(order_id)
            if normalised in self.session.checked_orders:
                status = self.session.checked_orders[normalised]["status"]

        result = self.search.search(query, order_status=status)
        self.session.retrieved_docs.update({h.chunk.doc_id: h.chunk.content for h in result.hits})
        self.trace.searches.append(
            {
                "query": query,
                "order_status_filter": status,
                "hits": [{"doc_id": h.chunk.doc_id, "score": round(h.score, 4)} for h in result.hits],
                "excluded": {c.chunk.doc_id: c.debug["excluded"] for c in result.candidates if "excluded" in c.debug},
                "timings_ms": result.timings_ms,
            }
        )
        response = {
            "query": query,
            "applied_order_status_filter": status,
            "results": [
                {"doc_id": h.chunk.doc_id, "title": h.chunk.title, "content": h.chunk.content, "relevance": round(h.score, 3)}
                for h in result.hits
            ],
        }
        if not result.found:
            response["note"] = "No relevant policy found. Do not answer this from general knowledge."
        return response

    def check_order_status(self, order_id: str) -> dict:
        order_id, error = self._resolve_order_id(order_id)
        if error:
            return error
        result = self._call_api(self.api.check_order_status, order_id)
        if "error" not in result:
            self.session.checked_orders[order_id] = result
        return result

    def _write_action(self, tool: str, order_id: str, reason: str) -> dict:
        order_id, error = self._resolve_order_id(order_id)
        if error:
            return error
        if self.session.write_tools_locked:
            return gate_error(
                "ACTIONS_DISABLED",
                "Account actions are disabled for this conversation because a message was flagged by safety checks. "
                "Explain that you cannot do this and offer a human agent.",
            )
        if order_id not in self.session.checked_orders:
            return gate_error("CHECK_STATUS_FIRST", f"Call check_order_status for {order_id} before {tool}.")
        if not reason or not reason.strip():
            return gate_error("REASON_REQUIRED", "Ask the customer for their reason first.")
        amount = self.session.checked_orders[order_id]["amount"]
        if amount > settings.high_value_threshold:
            ticket = self.escalate_to_human(
                f"{tool} on high-value order ({amount:.0f}) requires human approval", f"{order_id}: {reason}"
            )
            return gate_error(
                "HUMAN_APPROVAL_REQUIRED",
                f"Orders above Rs {settings.high_value_threshold:,.0f} need a support agent to approve this. The request "
                f"has been passed to an agent (reference {ticket['ticket_id']}); tell the customer.",
            )

        api_fn = getattr(self.api, tool)
        pending = self.session.pending_action
        confirmed = (
            pending is not None
            and pending["tool"] == tool
            and pending["order_id"] == order_id
            and pending["turn"] < self.session.turn
            and is_affirmative(self.session.customer_messages[-1])
        )
        if confirmed:
            self.session.pending_action = None
            return self._call_api(api_fn, order_id, pending["reason"])

        # Not yet confirmed: validate eligibility now so we never ask the customer to confirm
        # something that will then be rejected.
        check = self._call_api(api_fn, order_id, reason, dry_run=True)
        if "error" in check:
            return check
        if "case_id" in check:  # an identical case already exists (idempotent API)
            return {**check, "note": "A case already exists for this order; no new case was created."}
        self.session.pending_action = {"tool": tool, "order_id": order_id, "reason": reason, "turn": self.session.turn}
        return {
            "status": "CONFIRMATION_REQUIRED",
            "message": (
                f"Not executed yet. {tool} is eligible for {order_id}. Summarise what will happen and ask the customer "
                "to confirm. Do not say it has been done."
            ),
        }

    def escalate_to_human(self, reason: str, summary: str = "") -> dict:
        digest = hashlib.sha256(f"{self.session.session_id}:{self.session.turn}".encode()).hexdigest()
        ticket = {"ticket_id": f"ESC-{int(digest, 16) % 100000:05d}", "status": "QUEUED_FOR_HUMAN_AGENT"}
        self.session.escalation = {**ticket, "reason": reason, "summary": summary}
        self.trace.escalated = True
        return ticket
