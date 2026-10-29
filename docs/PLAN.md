# Implementation Plan — Order Support Assistant

> This is the plan as written before implementation, kept for reference. Some decisions changed once
> measured: the model is `deepseek/deepseek-v4.1-flash-1017` rather than Claude Sonnet (same eval pass
> rate at ~1/39th of the cost), and the order-status score nudge became a hard filter. See
> [DESIGN.md](DESIGN.md) for what was built and why.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11 (venv via `uv`) | Brief suggests Python stubs; ML libs are Python-first |
| Embeddings (bi-encoder) | `BAAI/bge-small-en-v1.5` (sentence-transformers) | Local, fast, no API cost |
| Keyword search | `rank_bm25` | The "hybrid" half of the reference diagram |
| Vector store | In-memory numpy | 8 docs; design doc covers what replaces it at scale |
| Reranker (cross-encoder) | `BAAI/bge-reranker-base` (fallback `cross-encoder/ms-marco-MiniLM-L-6-v2`) | Brief requires a cross-encoder-class model |
| LLM gateway | OpenRouter (OpenAI-compatible API, `openai` SDK) | Keys available; model swappable via env var |
| Orchestrator model | `anthropic/claude-sonnet-5.5` | Reliable tool calling + argument extraction |
| Cheap model (optional) | `anthropic/claude-haiku-5.5` | Cost lever for simple FAQ turns |
| Tests / evals | `pytest` + scenario runner | Regression net for the brief's example queries |
| Interface | CLI | UI is explicitly not evaluated |

Retrieval, reranking, tools and guardrails run without an API key; only the agent loop needs `OPENROUTER_API_KEY`.

## Repo layout

```
data/corpus.json             8 docs + enriched metadata
data/mock_orders.json        seeded orders, one per scenario
assistant/
  config.py                  models, thresholds, fixed "now" clock, session customer
  llm.py                     OpenRouter client wrapper
  corpus.py                  loading + chunking
  retrieval.py               BM25 + dense + RRF fusion
  reranker.py                cross-encoder stage
  tools/                     schemas.py, commerce_api.py, executor.py (policy gates)
  guardrails.py              injection, PII redaction, scope, ownership
  orchestrator.py            agent loop
  synthesis.py               grounded answer + citation check
  audit.py                   JSONL audit log
  cli.py
evals/                       scenarios.yaml, run_evals.py, retrieval_compare.py
tests/
docs/                        PLAN.md, DESIGN.md, ASSUMPTIONS.md
```

## Phase 0 — Setup (~0.5h)
- Scaffold, venv, deps, `.env.example`.
- Fixed simulated clock (`NOW`) and session customer (`CUST-001`) in config so timeline and ownership logic are deterministic.
- `python -m assistant ping` verifies OpenRouter connectivity.

**Exit:** deps install, CLI runs, ping succeeds.

## Phase 1 — Corpus, chunking, mock API (~1h)
- Enrich each doc with metadata: `topic`, `applies_to_status`, `window`, `trigger`, `not_for`.
- Chunking: one chunk per doc, title prepended, no overlap — each doc is one atomic policy; splitting would separate a condition from its timeline. Document section-aware ~300-token / ~15% overlap for longer future docs.
- Mock commerce API backed by `mock_orders.json`:

| Order | Owner | State | Exercises |
|---|---|---|---|
| ORD-4521 | CUST-001 | PAYMENT_FAILED | example payload, "both" query |
| ORD-7701 | CUST-001 | RETURN_RECEIVED_AT_WAREHOUSE | tool → DOC-1 grounding |
| ORD-5000 | CUST-001 | PAYMENT_FAILED, Rs 5000, 3 days ago | past 48h → offer dispute |
| ORD-6100 | CUST-001 | international return | DOC-6 (+2–3 days) |
| ORD-9999 | CUST-002 | any | someone else's order |
| ORD-0000 | — | not found | injection query |
| ORD-1313 | CUST-001 | raises timeout | tool-failure path |

- Add `raise_dispute(order_id, reason)` stub (in the reference diagram; needed by example query 3) — recorded as an assumption.

**Exit:** tools return the brief's JSON shapes; unit tests pass.

## Phase 2 — Retrieval + reranking (~1.5h) ⭐
1. Hybrid first stage: BM25 + dense cosine, fused with Reciprocal Rank Fusion, top-k=8.
2. Cross-encoder rerank of (query, title+chunk) pairs → top-3, with a minimum relevance threshold ("no policy found" instead of guessing).
3. Metadata-aware boost when a tool has returned an order status (PAYMENT_FAILED → DOC-2, RETURN_RECEIVED → DOC-1).
4. `evals/retrieval_compare.py`: BM25 vs dense vs hybrid vs hybrid+rerank rank tables for the trap query and the brief's examples. If the bi-encoder does not actually fail on 8 docs, report that honestly and add distractor docs to show the failure.

**Exit:** DOC-2 is #1 after rerank for the trap query (asserted in a test); comparison table saved for the design doc.

## Phase 3 — Tool calling + orchestration (~2h) ⭐
Single LLM agent loop with tools `search_policy`, `check_order_status`, `initiate_return`, `raise_dispute`, `escalate_to_human`. The LLM proposes; deterministic gates in `executor.py` decide:
- **No hallucinated IDs:** `order_id` must appear verbatim (normalized `ORD-?\d{4}`) in customer messages.
- **Ownership:** order owner must equal session customer; otherwise a generic "can't find that order" (no existence leak).
- **Write preconditions:** `initiate_return` / `raise_dispute` require a prior `check_order_status` this session, an eligible state, a customer-stated reason, and explicit confirmation.
- **Tool errors:** one retry with backoff, then a structured error; the model must say it couldn't check and offer escalation.
- **Unsupported capabilities** (password reset): no tool exists; answer from DOC-4.

Grounded synthesis: every policy claim cites `[DOC-n]`; a post-check verifies cited IDs were in this turn's reranked set (regenerate once, then safe fallback / escalate). Tool facts cite `[ORDER]`.

Missing info: answer the policy part, then ask for the order ID before any tool call or offer.

**Exit:** all five §9 example queries behave correctly end to end.

## Phase 4 — Guardrails + audit (~1h)
- Pre-LLM: injection heuristics flag the turn and disable write tools; PII redaction (card numbers, phone, email, UPI) before anything reaches OpenRouter.
- Customer text passed as delimited untrusted content; code gates are the real defense.
- Escalation triggers: explicit human request; ≥2 tool or grounding failures; low reranker confidence; dispute past window (DOC-8); high-value refunds; injection + write intent; anger/legal language.
- Audit JSONL per turn: trace ID, customer, redacted query, retrieved/reranked IDs + scores, tool calls (args, results, gate decisions), guardrail flags, response, model IDs, per-stage latency.

**Exit:** the ORD-0000 injection query is refused with an explanation, no tool call, and an audit line showing why.

## Phase 5 — Evals + hardening (~1h)
- `evals/scenarios.yaml`, 15–20 cases asserting tools called / not called, cited docs, must-include / must-not-include phrases.
- Capture real per-stage latency for the design doc.

**Exit:** eval report prints; failures are listed as known gaps.

## Phase 6 — Design doc + supporting docs (~1.5–2h)
- `DESIGN.md` (4–8 pages → PDF): architecture and departures from the reference (RAG-as-a-tool, gates in code), retrieval and reranking with the real comparison table, tool decisioning, guardrails, latency / cost / audit / 50× scale, what's not in v1.
- `ASSUMPTIONS.md`: assumptions, what I'd do with more time, kickoff questions.
- `README.md`: setup, run, evals, total time spent.

## Risks

| Risk | Mitigation |
|---|---|
| Trap query doesn't fail for the bi-encoder on 8 docs | Report honestly; add distractor docs |
| Reviewers lack an API key | Non-LLM components and tests run keyless; model configurable via OpenRouter |
| LLM non-determinism in evals | `temperature=0`; assert on tool calls and citations, not wording |
| Scope creep | Phases 2–3 carry most of the marks; protect their time |
