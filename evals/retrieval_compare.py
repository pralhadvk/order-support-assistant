"""Compare retrieval configurations on the labelled query set.

    python -m evals.retrieval_compare

Writes evals/results/retrieval_compare.md (used in the design doc) and prints the same report.
"""

from pathlib import Path

import numpy as np
import yaml

from assistant.corpus import build_chunks
from assistant.reranker import Reranker
from assistant.retrieval import HybridRetriever
from assistant.search import MIN_RELEVANCE, PolicySearch

HERE = Path(__file__).parent
STATUS_DEMO_QUERY = "How long will it take to get my money back for my order?"


def rank_ids(ids: list[str], scores) -> list[str]:
    return [ids[i] for i in np.argsort(-np.asarray(scores), kind="stable")]


def main() -> None:
    cases = yaml.safe_load((HERE / "retrieval_queries.yaml").read_text())
    chunks = build_chunks()
    ids = [c.doc_id for c in chunks]
    retriever = HybridRetriever(chunks)
    plain_reranker = Reranker(model=None, use_metadata=False)
    meta_reranker = Reranker(model=plain_reranker.model, use_metadata=True)

    def rankings(query: str) -> dict[str, tuple[list[str], float | None]]:
        hybrid = retriever.retrieve(query)
        plain = plain_reranker.rerank(query, hybrid)
        meta = meta_reranker.rerank(query, hybrid)
        return {
            "BM25 only": (rank_ids(ids, retriever.bm25_scores(query)), None),
            "Bi-encoder only": (rank_ids(ids, retriever.dense_scores(query)), None),
            "Hybrid (RRF)": ([c.chunk.doc_id for c in hybrid], None),
            "Hybrid + rerank": ([c.chunk.doc_id for c in plain], plain[0].score),
            "Hybrid + rerank + metadata": ([c.chunk.doc_id for c in meta], meta[0].score),
        }

    results = [(case, rankings(case["query"])) for case in cases]
    configs = list(results[0][1])
    in_scope = [(c, r) for c, r in results if c["gold"]]
    out_scope = [(c, r) for c, r in results if not c["gold"]]

    lines = ["# Retrieval comparison", "", f"{len(in_scope)} in-scope queries, {len(out_scope)} out-of-scope.", ""]
    lines += ["| Configuration | Top-1 accuracy | MRR | Gold in top-3 | Trap group top-1 | Out-of-scope rejected |"]
    lines += ["|---|---|---|---|---|---|"]
    for cfg in configs:
        ranks = [r[cfg][0].index(c["gold"]) + 1 for c, r in in_scope]
        trap = [r[cfg][0][0] == c["gold"] for c, r in in_scope if c["group"] == "trap"]
        if out_scope[0][1][cfg][1] is not None:
            rejected = f"{sum(r[cfg][1] < MIN_RELEVANCE for _, r in out_scope)}/{len(out_scope)}"
        else:
            rejected = "n/a (no calibrated score)"
        lines.append(
            f"| {cfg} | {sum(x == 1 for x in ranks)}/{len(ranks)} | {np.mean([1 / x for x in ranks]):.3f} "
            f"| {sum(x <= 3 for x in ranks)}/{len(ranks)} | {sum(trap)}/{len(trap)} | {rejected} |"
        )

    lines += ["", "## Per-query top-1 (✗ = wrong document ranked first)", ""]
    lines += ["| Query | Gold | " + " | ".join(configs) + " |", "|---|---|" + "---|" * len(configs)]
    for case, r in in_scope:
        cells = [f"{r[cfg][0][0]}{'' if r[cfg][0][0] == case['gold'] else ' ✗'}" for cfg in configs]
        lines.append(f"| {case['query']} | {case['gold']} | " + " | ".join(cells) + " |")

    lines += ["", "## Top cross-encoder score for out-of-scope queries", ""]
    for case, r in out_scope:
        lines.append(f"- \"{case['query']}\": {r['Hybrid + rerank + metadata'][1]:.4f} (threshold {MIN_RELEVANCE})")

    search = PolicySearch(chunks, retriever=retriever, reranker=meta_reranker)
    lines += ["", f"## Status-aware filtering: \"{STATUS_DEMO_QUERY}\"", ""]
    lines += ["| Order status from tool | Hits passed to synthesis |", "|---|---|"]
    for status in [None, "PAYMENT_FAILED", "RETURN_RECEIVED"]:
        hits = search.search(STATUS_DEMO_QUERY, order_status=status).hits
        lines.append(f"| {status or '(none)'} | " + ", ".join(f"{h.chunk.doc_id} ({h.score:.2f})" for h in hits) + " |")

    timings = [search.search(c["query"]).timings_ms for c in cases]
    lines += ["", "## Latency (CPU, this machine, 8 chunks)", ""]
    for stage in ["retrieve", "rerank"]:
        values = [t[stage] for t in timings]
        lines.append(f"- {stage}: median {np.median(values):.0f} ms, max {max(values):.0f} ms")

    report = "\n".join(lines) + "\n"
    out = HERE / "results" / "retrieval_compare.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
