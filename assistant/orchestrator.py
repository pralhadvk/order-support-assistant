"""Agent loop: LLM proposes tool calls, the executor gates and runs them, synthesis is grounding-checked.

Departure from the reference diagram: instead of a separate intent router in front of two fixed
pipelines, the RAG path is a tool. Routing becomes the model's tool choice, which handles queries that
need both paths (status lookup, then the policy for that status) without a third hard-coded route.
The safety-relevant decisions the router would have made are enforced by the executor instead.
"""

import json
import time
from dataclasses import dataclass

from assistant import guardrails, llm
from assistant.audit import AuditLog
from assistant.config import settings
from assistant.prompts import system_prompt
from assistant.search import PolicySearch
from assistant.session import Session, TurnTrace
from assistant.synthesis import check_grounding
from assistant.tools.commerce_api import MockCommerceAPI
from assistant.tools.executor import ToolExecutor
from assistant.tools.schemas import ALL_TOOLS

MAX_STEPS = 8

GROUNDING_RETRY_NOTE = (
    "[Automated grounding check, not from the customer] Your draft reply {problems}. Rewrite it so every policy "
    "or timeline statement is supported by a search_policy result already in this conversation and carries its "
    "citation, or remove the statement. Reply with the revised message only."
)
# Includes the ticket ID so later turns (and the model reading history) know the handoff really happened.
FALLBACK_ANSWER = (
    "I'm sorry, I couldn't put together a reliable answer for this. I've passed your conversation to a "
    "support agent, who will pick it up from here (reference {ticket_id})."
)
HANDOFF_ANSWER = (
    "Of course. I've passed your conversation to a support agent, who will have the full context "
    "(reference {ticket_id})."
)
ADDED_ESCALATION_NOTE = (
    "I've also passed this conversation to a support agent so a person can follow up (reference {ticket_id})."
)


@dataclass
class TurnResult:
    answer: str
    trace: TurnTrace


class Assistant:
    def __init__(
        self,
        api: MockCommerceAPI | None = None,
        search: PolicySearch | None = None,
        chat_fn=None,
        audit: AuditLog | None = None,
        model: str | None = None,
    ):
        self.api = api or MockCommerceAPI()
        self.search = search or PolicySearch()
        self.chat = chat_fn or llm.chat
        self.audit = audit or AuditLog()
        self.model = model or settings.orchestrator_model

    def respond(self, session: Session, message: str) -> TurnResult:
        start = time.perf_counter()
        report = guardrails.inspect(message)
        # Raw text stays in-process (the order-ID gate needs it); only redacted text reaches the LLM and the log.
        session.customer_messages.append(message)
        session.messages.append({"role": "user", "content": report.wrapped_for_llm()})
        trace = TurnTrace(session.session_id, session.turn, report.redacted_text, guardrails=report.to_dict(), model=self.model)
        executor = ToolExecutor(self.api, self.search, session, trace)
        if report.injection_signals:
            session.write_tools_locked = True  # sticky for the session: one flagged message taints later "confirmations"

        if report.wants_human:
            # Deterministic: an explicit request for a person never depends on the model agreeing.
            answer = self._handoff(session, executor)
        else:
            answer = self._run_loop(session, executor, trace)
            if answer is None:
                answer = self._fallback(executor, "agent loop did not converge")
            else:
                answer = self._enforce_grounding(session, executor, trace, answer)
            answer = self._post_turn_escalation(session, executor, report, answer)

        session.messages.append({"role": "assistant", "content": answer})
        trace.answer = answer
        self.audit.record(session, trace, report.redacted_text, (time.perf_counter() - start) * 1000)
        return TurnResult(answer, trace)

    def _handoff(self, session: Session, executor: ToolExecutor) -> str:
        ticket = session.escalation or executor.execute(
            "escalate_to_human", {"reason": "customer asked for a human agent", "summary": executor.trace.customer_message}
        )
        return HANDOFF_ANSWER.format(ticket_id=ticket["ticket_id"])

    def _post_turn_escalation(self, session: Session, executor: ToolExecutor, report, answer: str) -> str:
        if session.escalation:
            return answer
        reasons = []
        if session.tool_failures >= settings.max_tool_failures:
            reasons.append("order service unavailable")
        if report.legal_or_complaint:
            reasons.append("legal or complaint language")
        if not reasons:
            return answer
        ticket = executor.execute("escalate_to_human", {"reason": "; ".join(reasons), "summary": executor.trace.customer_message})
        return f"{answer}\n\n" + ADDED_ESCALATION_NOTE.format(ticket_id=ticket["ticket_id"])

    def _call_llm(self, messages: list[dict], trace: TurnTrace, tools=ALL_TOOLS):
        start = time.perf_counter()
        response = self.chat([{"role": "system", "content": system_prompt()}, *messages], tools=tools, model=self.model)
        msg = response.choices[0].message
        usage = response.usage
        trace.llm_calls.append(
            {
                "ms": round((time.perf_counter() - start) * 1000),
                "tool_calls": [tc.function.name for tc in msg.tool_calls or []],
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "cost_usd": getattr(usage, "cost", None),
            }
        )
        return msg

    def _run_loop(self, session: Session, executor: ToolExecutor, trace: TurnTrace) -> str | None:
        for _ in range(MAX_STEPS):
            msg = self._call_llm(session.messages, trace)
            if not msg.tool_calls:
                return msg.content or ""

            session.messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = executor.execute(tc.function.name, args)
                except json.JSONDecodeError:
                    result = {"error": {"code": "INVALID_ARGUMENTS", "message": "Arguments were not valid JSON."}}
                session.messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
        return None

    def _enforce_grounding(self, session: Session, executor: ToolExecutor, trace: TurnTrace, answer: str) -> str:
        result = check_grounding(answer, session.retrieved_docs, session.customer_messages)
        trace.grounding = {"first_pass": result.to_dict()}
        if result.ok:
            return answer

        # One rewrite, without tools: the model may only drop or cite claims, not fetch new ones.
        # The validator note is not persisted in the conversation history.
        retry_messages = [
            *session.messages,
            {"role": "assistant", "content": answer},
            {"role": "user", "content": GROUNDING_RETRY_NOTE.format(problems=result.feedback())},
        ]
        revised = self._call_llm(retry_messages, trace, tools=None).content or ""
        second = check_grounding(revised, session.retrieved_docs, session.customer_messages)
        trace.grounding["second_pass"] = second.to_dict()
        if second.ok:
            return revised
        return self._fallback(executor, f"grounding check failed twice: {second.feedback()}")

    def _fallback(self, executor: ToolExecutor, reason: str) -> str:
        ticket = executor.execute("escalate_to_human", {"reason": reason, "summary": executor.trace.customer_message})
        return FALLBACK_ANSWER.format(ticket_id=ticket["ticket_id"])
