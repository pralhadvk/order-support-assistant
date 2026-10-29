"""Retrieval behaviour tests. These load the real embedding and cross-encoder models (cached after first run)."""

import pytest

from assistant.search import PolicySearch


@pytest.fixture(scope="module")
def search():
    return PolicySearch()


def top_doc(result):
    return result.hits[0].chunk.doc_id if result.hits else None


@pytest.mark.parametrize(
    "query",
    [
        "my money got deducted and the order failed, when will I get it back",  # the brief's trap query
        "I was charged but the order didn't go through, where is my refund?",  # paraphrase the bi-encoder gets wrong
    ],
)
def test_failed_payment_queries_resolve_to_doc2(search, query):
    assert top_doc(search.search(query)) == "DOC-2"


def test_pure_rag_order_limit(search):
    assert top_doc(search.search("What's the maximum amount a single order can be?")) == "DOC-5"


def test_order_status_overrides_wording(search):
    query = "How long will it take to get my money back for my order?"
    failed = [h.chunk.doc_id for h in search.search(query, order_status="PAYMENT_FAILED").hits]
    returned = [h.chunk.doc_id for h in search.search(query, order_status="RETURN_RECEIVED").hits]
    assert failed[0] == "DOC-2" and "DOC-1" not in failed
    assert returned[0] == "DOC-1" and "DOC-2" not in returned


def test_excluded_chunks_are_explained_for_audit(search):
    result = search.search("when will my refund come", order_status="PAYMENT_FAILED")
    doc1 = next(c for c in result.candidates if c.chunk.doc_id == "DOC-1")
    assert "scoped to" in doc1.debug["excluded"]


@pytest.mark.parametrize("query", ["what's the weather like in Mumbai", "how do I invest in mutual funds"])
def test_out_of_scope_returns_no_hits(search, query):
    assert not search.search(query).found
