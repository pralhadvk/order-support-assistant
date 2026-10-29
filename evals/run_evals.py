"""End-to-end scenario evals against live models via OpenRouter.

    python -m evals.run_evals                                  # default model
    python -m evals.run_evals --models openai/gpt-6-luna qwen/qwen3.8-flash
    python -m evals.run_evals --scenarios trap_failed_payment both_policy_and_status
    python -m evals.run_evals --repeat 3                       # consistency

Writes evals/results/model_comparison.md (summary) and evals/results/runs/<model>.json (full detail).
Checks assert on behaviour (tools, actions, citations, key facts), never on exact wording.
"""

import argparse
import json
import math
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from assistant.audit import AuditLog
from assistant.config import settings
from assistant.orchestrator import Assistant
from assistant.search import PolicySearch
from assistant.session import Session
from assistant.tools.executor import WRITE_TOOLS

HERE = Path(__file__).parent
RESULTS = HERE / "results"
DOC_REF = re.compile(r"DOC-\d+")


def check_turn(expect: dict, result, session: Session) -> list[str]:
    trace, answer = result.trace, result.answer
    lower = answer.lower()
    attempted = {c["tool"] for c in trace.tool_calls}
    executed = {
        c["tool"] for c in trace.tool_calls if c["tool"] in WRITE_TOOLS and "case_id" in c["result"] and "note" not in c["result"]
    }
    cited = set(DOC_REF.findall(answer))
    error_codes = {c["result"].get("error", {}).get("code") for c in trace.tool_calls} - {None}

    failures = []
    for tool in expect.get("tools_called", []):
        if tool not in attempted:
            failures.append(f"expected {tool} to be called")
    for tool in expect.get("tools_not_called", []):
        if tool in attempted:
            failures.append(f"{tool} should not be called")
    if "actions_executed" in expect and executed != set(expect["actions_executed"]):
        failures.append(f"executed {sorted(executed)}, expected {expect['actions_executed']}")
    for doc in expect.get("cites", []):
        if doc not in cited:
            failures.append(f"missing citation {doc}")
    for doc in expect.get("not_cites", []):
        if doc in cited:
            failures.append(f"should not cite {doc}")
    if expect.get("no_citations") and cited:
        failures.append(f"should cite nothing, cited {sorted(cited)}")
    for group in expect.get("include", []):
        if not any(p.lower() in lower for p in group):
            failures.append(f"reply lacks any of {group}")
    for phrase in expect.get("exclude", []):
        if phrase.lower() in lower:
            failures.append(f"reply contains '{phrase}'")
    if "escalated" in expect and trace.escalated != expect["escalated"]:
        failures.append(f"escalated={trace.escalated}, expected {expect['escalated']}")
    if "session_escalated" in expect and (session.escalation is not None) != expect["session_escalated"]:
        failures.append(f"conversation escalated={session.escalation is not None}, expected {expect['session_escalated']}")
    if "injection_flagged" in expect and bool(trace.guardrails.get("injection_signals")) != expect["injection_flagged"]:
        failures.append("injection flag mismatch")
    for code in expect.get("no_error_codes", []):
        if code in error_codes:
            failures.append(f"error {code} occurred")
    return failures


def run_model(model: str, scenarios: list[dict], search: PolicySearch, repeat: int = 1) -> dict:
    safe = model.replace("/", "__")
    audit = AuditLog(settings.log_dir / "eval" / f"{safe}.jsonl")
    audit.path.unlink(missing_ok=True)  # the latency report reads this file, so it should hold this run only
    runs = []
    for scenario in scenarios:
        for repetition in range(1, repeat + 1):
            assistant = Assistant(search=search, audit=audit, model=model)  # fresh mock API state per run
            session = Session()
            turns = []
            for turn in scenario["turns"]:
                start = time.perf_counter()
                try:
                    result = assistant.respond(session, turn["say"])
                    failures = check_turn(turn.get("expect", {}), result, session)
                    trace = result.trace
                    record = {
                        "say": turn["say"],
                        "answer": result.answer,
                        "failures": failures,
                        "tools": [(c["tool"], c["args"], c["result"].get("error", {}).get("code")) for c in trace.tool_calls],
                        "grounded_first_pass": trace.grounding.get("first_pass", {}).get("ok", True),
                        "llm_calls": len(trace.llm_calls),
                        "cost_usd": sum(c.get("cost_usd") or 0 for c in trace.llm_calls),
                    }
                except Exception as exc:  # a provider error is a failed turn, not a crashed eval
                    record = {"say": turn["say"], "answer": "", "failures": [f"exception: {exc!r}"[:300]], "llm_calls": 0, "cost_usd": 0}
                record["seconds"] = round(time.perf_counter() - start, 2)
                turns.append(record)
            runs.append(
                {"id": scenario["id"], "run": repetition, "passed": all(not t["failures"] for t in turns), "turns": turns}
            )

    out = RESULTS / "runs" / f"{safe}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": model, "scenarios": runs}, indent=2))
    return {"model": model, "scenarios": runs}


def summarise(results: list[dict], repeat: int) -> str:
    lines = ["# Model comparison", "", f"Simulated now: {settings.now:%Y-%m-%d %H:%M} UTC. {repeat} run(s) per scenario (temperature 0).", ""]
    lines += ["| Model | Scenario runs passed | Checks failed | Grounded 1st try | Median s/turn | p90 s/turn | Avg LLM calls/turn | Cost/turn (USD) |"]
    lines += ["|---|---|---|---|---|---|---|---|"]
    for r in results:
        turns = [t for s in r["scenarios"] for t in s["turns"] if t.get("llm_calls")]
        secs = sorted(t["seconds"] for t in turns) or [0]
        grounded = [t.get("grounded_first_pass", True) for t in turns]
        passed = sum(s["passed"] for s in r["scenarios"])
        failed_checks = sum(len(t["failures"]) for s in r["scenarios"] for t in s["turns"])
        lines.append(
            f"| `{r['model']}` | {passed}/{len(r['scenarios'])} | {failed_checks} | {sum(grounded)}/{len(grounded)} "
            f"| {statistics.median(secs):.1f} | {secs[math.ceil(0.9 * len(secs)) - 1]:.1f} "
            f"| {statistics.mean(t['llm_calls'] for t in turns) if turns else 0:.1f} "
            f"| {statistics.mean(t['cost_usd'] for t in turns) if turns else 0:.5f} |"
        )

    ids = list(dict.fromkeys(s["id"] for s in results[0]["scenarios"]))
    lines += ["", "## Per-scenario results (runs passed)", "", "| Scenario | " + " | ".join(f"`{r['model'].split('/')[-1]}`" for r in results) + " |"]
    lines += ["|---|" + "---|" * len(results)]
    for sid in ids:
        cells = []
        for r in results:
            runs = [s for s in r["scenarios"] if s["id"] == sid]
            passed = sum(s["passed"] for s in runs)
            cells.append(f"{'✓' if passed == len(runs) else '✗'} {passed}/{len(runs)}")
        lines.append(f"| {sid} | " + " | ".join(cells) + " |")

    lines += ["", "## Failures", ""]
    for r in results:
        for s in r["scenarios"]:
            for n, t in enumerate(s["turns"], 1):
                if t["failures"]:
                    lines.append(f"- `{r['model']}` / {s['id']} run {s['run']} turn {n}: " + "; ".join(t["failures"]))
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=[settings.orchestrator_model])
    parser.add_argument("--scenarios", nargs="+", help="scenario ids to run (default: all)")
    parser.add_argument("--repeat", type=int, default=1, help="runs per scenario, to measure consistency")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", default="model_comparison.md")
    args = parser.parse_args()

    scenarios = yaml.safe_load((HERE / "scenarios.yaml").read_text())
    if args.scenarios:
        scenarios = [s for s in scenarios if s["id"] in args.scenarios]
    search = PolicySearch()  # models loaded once, shared across threads (inference only)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda m: run_model(m, scenarios, search, args.repeat), args.models))

    report = summarise(results, args.repeat)
    (RESULTS / args.out).write_text(report)
    print(report)


if __name__ == "__main__":
    main()
