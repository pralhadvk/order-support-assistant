"""Per-conversation state and per-turn trace."""

from dataclasses import dataclass, field
from uuid import uuid4

from assistant.config import settings


@dataclass
class Session:
    customer_id: str = settings.session_customer_id  # from authentication, never from the model
    session_id: str = field(default_factory=lambda: uuid4().hex[:12])
    messages: list[dict] = field(default_factory=list)  # LLM-visible history (system prompt added per call)
    customer_messages: list[str] = field(default_factory=list)  # raw customer text, source for order-ID checks
    checked_orders: dict[str, dict] = field(default_factory=dict)  # order_id -> latest check_order_status result
    retrieved_docs: dict[str, str] = field(default_factory=dict)  # doc_id -> content the model has legitimately seen
    pending_action: dict | None = None  # write action awaiting customer confirmation
    write_tools_locked: bool = False  # set by guardrails when a turn looks like an injection attempt
    tool_failures: int = 0
    escalation: dict | None = None

    @property
    def turn(self) -> int:
        return len(self.customer_messages)


@dataclass
class TurnTrace:
    session_id: str
    turn: int
    customer_message: str
    tool_calls: list[dict] = field(default_factory=list)
    searches: list[dict] = field(default_factory=list)
    llm_calls: list[dict] = field(default_factory=list)
    grounding: dict = field(default_factory=dict)
    guardrails: dict = field(default_factory=dict)
    answer: str = ""
    escalated: bool = False
    model: str = ""
