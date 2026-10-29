"""The full RAG retrieval path: hybrid retrieve -> cross-encoder rerank -> status filter -> threshold."""

import time
from dataclasses import dataclass, field

from assistant.config import settings
from assistant.corpus import Chunk, build_chunks
from assistant.reranker import Reranker
from assistant.retrieval import Candidate, HybridRetriever

# Calibrated on evals/retrieval_queries.yaml: in-scope single-intent queries score >= ~0.14 at top-1,
# out-of-scope queries ~0.000. Deliberately low so multi-intent phrasing still gets through;
# the orchestrator decomposes compound questions into focused searches.
MIN_RELEVANCE = 0.01


@dataclass
class SearchResult:
    query: str
    hits: list[Candidate]  # what synthesis is allowed to use
    candidates: list[Candidate]  # full reranked list incl. excluded chunks, for audit
    timings_ms: dict = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return bool(self.hits)


def applies_to(chunk: Chunk, order_status: str) -> bool:
    """A policy scoped to specific order statuses only applies to those; unscoped policies always apply.

    This is a hard filter rather than a score nudge: once a tool has returned the order's status, that
    record is ground truth, and no amount of wording overlap makes DOC-1 ("returned items") the right
    answer for a PAYMENT_FAILED order. Measured in evals/retrieval_compare.py: a +/-0.3 nudge still let
    DOC-1 win for a failed payment.
    """
    scoped_to = chunk.metadata.get("applies_to_status") or []
    return not scoped_to or order_status in scoped_to


class PolicySearch:
    def __init__(self, chunks: list[Chunk] | None = None, retriever=None, reranker=None):
        chunks = chunks if chunks is not None else build_chunks()
        self.retriever = retriever or HybridRetriever(chunks)
        self.reranker = reranker or Reranker()

    def search(self, query: str, order_status: str | None = None, top_n: int | None = None) -> SearchResult:
        top_n = top_n or settings.rerank_top_n
        t0 = time.perf_counter()
        first_stage = self.retriever.retrieve(query)
        t1 = time.perf_counter()
        reranked = self.reranker.rerank(query, first_stage)
        t2 = time.perf_counter()

        eligible = []
        for c in reranked:
            if order_status and not applies_to(c.chunk, order_status):
                c.debug["excluded"] = f"scoped to {c.chunk.metadata['applies_to_status']}, order is {order_status}"
            elif c.score < MIN_RELEVANCE:
                c.debug["excluded"] = "below relevance threshold"
            else:
                eligible.append(c)

        return SearchResult(
            query=query,
            hits=eligible[:top_n],
            candidates=reranked,
            timings_ms={"retrieve": round((t1 - t0) * 1000, 1), "rerank": round((t2 - t1) * 1000, 1)},
        )
