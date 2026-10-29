"""First-stage retrieval: BM25 (lexical) + bi-encoder (dense), fused with Reciprocal Rank Fusion.

This stage is optimised for recall and speed, not precision. Both signals score the query and each
chunk independently, so they reward shared vocabulary/topic ("refund", "money back") rather than
whether the chunk's conditions match the customer's situation. Precision is the reranker's job.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from assistant.config import settings
from assistant.corpus import Chunk

# bge-*-v1.5 models are trained with this instruction on the query side only.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RRF_K = 60
STOPWORDS = frozenset(
    "a an and are as at be but by can do for from has have how i if in is it its my of on or "
    "the this to was what when where which will with you your me".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model)


@dataclass
class Candidate:
    chunk: Chunk
    score: float
    debug: dict = field(default_factory=dict)  # per-stage ranks and scores, for explainability and audit


def _ranks(scores: np.ndarray) -> np.ndarray:
    """1-based rank of each position (1 = highest score)."""
    order = np.argsort(-scores, kind="stable")
    ranks = np.empty_like(order)
    ranks[order] = np.arange(1, len(scores) + 1)
    return ranks


class HybridRetriever:
    def __init__(self, chunks: list[Chunk], embedder: SentenceTransformer | None = None):
        self.chunks = chunks
        self.embedder = embedder or get_embedder()
        self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks])
        self.doc_vectors = self.embedder.encode([c.text for c in chunks], normalize_embeddings=True)

    def bm25_scores(self, query: str) -> np.ndarray:
        return np.asarray(self.bm25.get_scores(tokenize(query)))

    def dense_scores(self, query: str) -> np.ndarray:
        q = self.embedder.encode(BGE_QUERY_PREFIX + query, normalize_embeddings=True)
        return self.doc_vectors @ q

    def retrieve(self, query: str, k: int | None = None) -> list[Candidate]:
        k = k or settings.retrieve_top_k
        bm25_rank = _ranks(self.bm25_scores(query))
        dense_rank = _ranks(self.dense_scores(query))
        fused = 1.0 / (RRF_K + bm25_rank) + 1.0 / (RRF_K + dense_rank)
        hybrid_rank = _ranks(fused)

        top = np.argsort(-fused, kind="stable")[:k]
        return [
            Candidate(
                self.chunks[i],
                float(fused[i]),
                {"bm25_rank": int(bm25_rank[i]), "dense_rank": int(dense_rank[i]), "hybrid_rank": int(hybrid_rank[i])},
            )
            for i in top
        ]
