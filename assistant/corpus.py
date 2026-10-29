"""Corpus loading and chunking.

Chunking strategy: each policy doc is one short, self-contained rule (30-50 words), so a doc becomes
exactly one chunk with its title prepended. Splitting would separate a condition from its timeline
("5-7 business days" from "after the item is received at the warehouse"), which is precisely the
context the reranker needs. Docs longer than MAX_CHUNK_WORDS fall back to an overlapping word window,
so the pipeline stays correct if longer policies are added later.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from assistant.config import settings

MAX_CHUNK_WORDS = 250
OVERLAP_WORDS = 40


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    content: str
    metadata: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """What gets embedded and keyword-indexed."""
        return f"{self.title}: {self.content}"

    @property
    def rerank_text(self) -> str:
        """What the cross-encoder reads: the policy plus its applicability metadata.

        Spelling out when a policy applies and when it does not gives the cross-encoder the
        situational contrast the raw text lacks (DOC-1 vs DOC-2 both talk about getting money back).
        """
        trigger, not_for = self.metadata.get("trigger"), self.metadata.get("not_for")
        parts = [self.text]
        if trigger:
            parts.append(f"Applies when: {trigger}.")
        if not_for:
            parts.append(f"Not for: {not_for}.")
        return " ".join(parts)


def load_corpus(path: Path | None = None) -> list[dict]:
    path = path or settings.data_dir / "corpus.json"
    return json.loads(path.read_text())


def chunk_doc(doc: dict, max_words: int = MAX_CHUNK_WORDS, overlap: int = OVERLAP_WORDS) -> list[Chunk]:
    words = doc["content"].split()
    if len(words) <= max_words:
        return [Chunk(f"{doc['id']}#0", doc["id"], doc["title"], doc["content"], doc.get("metadata", {}))]

    chunks, start, step = [], 0, max_words - overlap
    while start < len(words):
        piece = " ".join(words[start : start + max_words])
        chunks.append(Chunk(f"{doc['id']}#{len(chunks)}", doc["id"], doc["title"], piece, doc.get("metadata", {})))
        if start + max_words >= len(words):
            break
        start += step
    return chunks


def build_chunks(docs: list[dict] | None = None) -> list[Chunk]:
    docs = docs if docs is not None else load_corpus()
    return [chunk for doc in docs for chunk in chunk_doc(doc)]
