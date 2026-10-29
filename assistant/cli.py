"""Command-line entry point: `python -m assistant <command>`."""

import argparse
import json
import sys

from assistant.config import settings
from assistant.llm import MissingAPIKeyError, chat
from assistant.session import Session, TurnTrace


def format_trace(trace: TurnTrace) -> str:
    lines = []
    flags = {k: v for k, v in trace.guardrails.items() if v}
    if flags:
        lines.append(f"  guardrails: {json.dumps(flags)}")
    for call in trace.tool_calls:
        result = call["result"]
        if "error" in result:
            outcome = f"✗ {result['error']['code']}"
        elif call["tool"] == "search_policy":
            outcome = "→ " + (", ".join(f"{r['doc_id']} ({r['relevance']})" for r in result["results"]) or "no results")
            if result.get("applied_order_status_filter"):
                outcome += f"  [filtered for {result['applied_order_status_filter']}]"
        else:
            outcome = "→ " + json.dumps({k: v for k, v in result.items() if k != "message"})
        lines.append(f"  {call['tool']}({json.dumps(call['args'])}) {outcome}")
    if trace.grounding:
        lines.append(f"  grounding: {json.dumps(trace.grounding)}")
    llm_ms = sum(c["ms"] for c in trace.llm_calls)
    lines.append(f"  llm calls: {len(trace.llm_calls)} ({llm_ms} ms)" + ("  ESCALATED" if trace.escalated else ""))
    return "\n".join(lines)


def _build_assistant():
    from assistant.orchestrator import Assistant  # deferred: loads the embedding and reranker models

    return Assistant()


def _respond(assistant, session: Session, query: str, show_trace: bool) -> None:
    result = assistant.respond(session, query)
    if show_trace:
        print(format_trace(result.trace))
    print(f"\nAssistant: {result.answer}\n")


def cmd_ping(_args) -> int:
    try:
        reply = chat([{"role": "user", "content": "Reply with the single word: pong"}])
    except MissingAPIKeyError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{settings.orchestrator_model}: {reply.choices[0].message.content}")
    return 0


def cmd_ask(args) -> int:
    _respond(_build_assistant(), Session(), args.query, args.trace)
    return 0


def cmd_chat(args) -> int:
    assistant, session = _build_assistant(), Session()
    print(f"Signed in as {session.customer_id}. Type 'quit' to exit.\n")
    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if query.lower() in {"quit", "exit"}:
            return 0
        if query:
            _respond(assistant, session, query, args.trace)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assistant", description="Order Support Assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ping", help="Verify OpenRouter connectivity").set_defaults(func=cmd_ping)

    ask = sub.add_parser("ask", help="Ask a single question")
    ask.add_argument("query")
    ask.add_argument("--trace", action="store_true", help="Show tool calls, gate decisions and grounding checks")
    ask.set_defaults(func=cmd_ask)

    chat_cmd = sub.add_parser("chat", help="Multi-turn conversation")
    chat_cmd.add_argument("--trace", action="store_true", help="Show tool calls, gate decisions and grounding checks")
    chat_cmd.set_defaults(func=cmd_chat)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
