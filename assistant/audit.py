"""Append-only JSONL audit log, one record per turn.

Contains only redacted customer text. Tool results are safe to log as-is: the order API never returns
customer PII, only order facts.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from assistant.config import settings
from assistant.session import Session, TurnTrace


class AuditLog:
    def __init__(self, path: Path | None = None):
        self.path = path or settings.log_dir / "audit.jsonl"

    def record(self, session: Session, trace: TurnTrace, redacted_message: str, total_ms: float) -> dict:
        entry = {
            "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "simulated_now": settings.now.isoformat(),
            "session_id": session.session_id,
            "customer_id": session.customer_id,
            "turn": trace.turn,
            "customer_message_redacted": redacted_message,
            "guardrails": trace.guardrails,
            "write_tools_locked": session.write_tools_locked,
            "searches": trace.searches,
            "tool_calls": trace.tool_calls,
            "grounding": trace.grounding,
            "escalation": session.escalation if trace.escalated else None,
            "answer": trace.answer,
            "models": {
                "orchestrator": trace.model,
                "embedding": settings.embedding_model,
                "reranker": settings.reranker_model,
            },
            "latency_ms": {
                "total": round(total_ms),
                "llm": sum(c["ms"] for c in trace.llm_calls),
                "llm_calls": len(trace.llm_calls),
                "llm_cost_usd": sum(c.get("cost_usd") or 0 for c in trace.llm_calls),
                "retrieve": round(sum(s["timings_ms"]["retrieve"] for s in trace.searches), 1),
                "rerank": round(sum(s["timings_ms"]["rerank"] for s in trace.searches), 1),
                "commerce_tools": round(sum(c["ms"] for c in trace.tool_calls if c["tool"] != "search_policy"), 1),
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return entry
