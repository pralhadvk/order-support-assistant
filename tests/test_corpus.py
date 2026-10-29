from assistant.corpus import build_chunks, chunk_doc


def test_each_policy_doc_is_one_chunk():
    chunks = build_chunks()
    assert [c.doc_id for c in chunks] == [f"DOC-{i}" for i in range(1, 9)]
    assert all(c.chunk_id.endswith("#0") for c in chunks)


def test_chunk_text_includes_title_and_metadata():
    doc2 = next(c for c in build_chunks() if c.doc_id == "DOC-2")
    assert doc2.text.startswith("Failed Payment - Amount Deducted:")
    assert doc2.metadata["applies_to_status"] == ["PAYMENT_FAILED"]


def test_long_doc_falls_back_to_overlapping_windows():
    doc = {"id": "DOC-X", "title": "Long", "content": " ".join(f"w{i}" for i in range(100))}
    chunks = chunk_doc(doc, max_words=40, overlap=10)
    assert [c.chunk_id for c in chunks] == ["DOC-X#0", "DOC-X#1", "DOC-X#2"]
    assert chunks[0].content.split()[-10:] == chunks[1].content.split()[:10]
    assert chunks[-1].content.split()[-1] == "w99"
