"""Per-stage latency and cost breakdown from an eval run's audit log.

    python -m evals.latency_report                      # default model
    python -m evals.latency_report --model openai/gpt-6-luna

Reads logs/eval/<model>.jsonl (written by run_evals) and writes evals/results/latency.md.
Turns answered without the LLM (deterministic human handoff) are excluded.
"""

import argparse
import json
import math
import statistics
from pathlib import Path

from assistant.config import settings

RESULTS = Path(__file__).parent / "results"
STAGES = ["llm", "retrieve", "rerank", "commerce_tools"]


def pct(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[math.ceil(q * len(values)) - 1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=settings.orchestrator_model)
    args = parser.parse_args()

    path = settings.log_dir / "eval" / f"{args.model.replace('/', '__')}.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    turns = [r["latency_ms"] for r in records if r["latency_ms"]["llm_calls"]]
    totals = [t["total"] for t in turns]
    total_sum = sum(totals)

    lines = [f"# Latency breakdown: `{args.model}`", "", f"{len(turns)} turns from {path.name}.", ""]
    lines += ["| Stage | Median ms/turn | p90 ms/turn | Share of total time |", "|---|---|---|---|"]
    for stage in STAGES:
        values = [t[stage] for t in turns]
        lines.append(f"| {stage} | {statistics.median(values):.0f} | {pct(values, 0.9):.0f} | {sum(values) / total_sum:.1%} |")
    other = [t["total"] - sum(t[s] for s in STAGES) for t in turns]
    lines.append(f"| other (guardrails, grounding check, orchestration) | {statistics.median(other):.0f} | {pct(other, 0.9):.0f} | {sum(other) / total_sum:.1%} |")
    lines.append(f"| **total** | **{statistics.median(totals):.0f}** | **{pct(totals, 0.9):.0f}** | 100% |")

    per_call = [t["llm"] / t["llm_calls"] for t in turns]
    calls = [t["llm_calls"] for t in turns]
    costs = [t.get("llm_cost_usd", 0) for t in turns]
    lines += [
        "",
        f"- LLM calls per turn: median {statistics.median(calls):.0f}, max {max(calls)}",
        f"- Latency per LLM call: median {statistics.median(per_call):.0f} ms, p90 {pct(per_call, 0.9):.0f} ms",
        f"- LLM cost per turn: mean ${statistics.mean(costs):.5f}, p90 ${pct(costs, 0.9):.5f}",
        f"- Projected LLM cost per 100k turns: ${statistics.mean(costs) * 100_000:,.0f}",
    ]

    report = "\n".join(lines) + "\n"
    (RESULTS / "latency.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
