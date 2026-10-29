"""Second-stage reranking with a cross-encoder.

A cross-encoder reads the query and the chunk together in one forward pass, so attention can relate
"order didn't go through" in the query to "order shows as failed/not placed" in the chunk, and notice
that "returned items" does not match. A bi-encoder cannot: it compresses each side to a vector
separately, so two chunks that are both about "getting money back" land close together. The
cross-encoder is too slow to score a whole corpus, which is why it only sees the first stage's top-k.
"""

from functools import lru_cache

from sentence_transformers import CrossEncoder

from assistant.config import settings
from assistant.retrieval import Candidate


@lru_cache(maxsize=1)
def get_cross_encoder() -> CrossEncoder:
    return CrossEncoder(settings.reranker_model)


class Reranker:
    def __init__(self, model: CrossEncoder | None = None, use_metadata: bool = True):
        self.model = model or get_cross_encoder()
        self.use_metadata = use_metadata

    def rerank(self, query: str, candidates: list[Candidate]) -> list[Candidate]:
        """Returns new Candidates ordered by cross-encoder relevance (sigmoid score in [0, 1])."""
        if not candidates:
            return []
        texts = [c.chunk.rerank_text if self.use_metadata else c.chunk.text for c in candidates]
        scores = self.model.predict([(query, t) for t in texts])
        rescored = [Candidate(c.chunk, float(s), {**c.debug, "rerank_score": round(float(s), 4)}) for c, s in zip(candidates, scores)]
        return sorted(rescored, key=lambda c: c.score, reverse=True)
