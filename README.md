# Order Support Assistant

An AI support assistant for an online retailer. It answers policy questions by retrieving and reranking the company's FAQ corpus, looks up and acts on orders by calling a mock commerce API, and enforces the rules that protect money and customer data in code rather than in the prompt.

- **Design document:** [docs/DESIGN.md](docs/DESIGN.md) (PDF: [docs/DESIGN.pdf](docs/DESIGN.pdf))
- **Assumptions and open questions:** [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md)
- **Evaluation results:** [evals/results/](evals/results/)

## Setup

Requires Python 3.11+ and an [OpenRouter](https://openrouter.ai) API key.

```bash
uv venv --python 3.11 .venv          # or: python3.11 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt   # or: .venv/bin/pip install -r requirements.txt
cp .env.example .env                 # then set OPENROUTER_API_KEY
.venv/bin/python -m assistant ping   # checks the key and model
```

The first run downloads the embedding and reranker models from Hugging Face (about 1.3 GB, cached afterwards).

The default model is `deepseek/deepseek-v4.1-flash-1017`. Any OpenRouter model with tool support works: set `ORCHESTRATOR_MODEL` in `.env`.

## Running it

```bash
# One question
.venv/bin/python -m assistant ask "How long will my refund take for order ORD-7701?"

# A conversation, showing tool calls, gate decisions and grounding checks
.venv/bin/python -m assistant chat --trace
```

You are signed in as customer `CUST-001`, and the simulated date is **Sunday 27 Sep 2026, 10:00 UTC**, so timeline answers are reproducible. Orders you can try:

| Order | State | Try asking |
|---|---|---|
| ORD-7701 | Return received, refund due by 2 Oct | "How long will my refund take for order ORD-7701?" |
| ORD-4521 | Payment failed, reversal overdue | "Your policy says 5-7 days but it's been 9 days for order #4521" |
| ORD-5000 | Payment failed 3 days ago, Rs 5000 | "My order of Rs 5000 failed 3 days ago, I want a chargeback" (then give the ID, then "yes") |
| ORD-2210 | Payment failed 14h ago, not overdue | "Can you raise a dispute for ORD-2210?" |
| ORD-6100 | International return, inside DOC-6's extension | "Is my refund for ORD-6100 late?" |
| ORD-3300 | Delivered, returnable | "I want to return ORD-3300, wrong size" (then "yes") |
| ORD-8800 | Delivered, Rs 45,000 | Return it: goes to a human (high-value) |
| ORD-1313 | Order service times out | Retry, then honest failure and handoff |
| ORD-9999 | Another customer's order | Indistinguishable from a missing order |

## Tests and evaluations

```bash
.venv/bin/python -m pytest                       # 67 tests; no API key needed, uses a scripted fake LLM where relevant
.venv/bin/python -m evals.retrieval_compare      # BM25 vs bi-encoder vs hybrid vs hybrid + rerank; no API key needed
.venv/bin/python -m evals.run_evals --repeat 3   # 21 end-to-end scenarios against the live model
.venv/bin/python -m evals.latency_report         # per-stage latency and cost from the last eval run
.venv/bin/python -m evals.run_evals --models openai/gpt-6-luna qwen/qwen3.8-flash   # compare models
```

## Layout

```
assistant/
  guardrails.py      PII redaction, injection/scope detection, human-request detection
  orchestrator.py    agent loop, grounding enforcement, escalation triggers, audit
  search.py          retrieval pipeline: hybrid retrieve -> rerank -> status filter -> threshold
  retrieval.py       BM25 + bi-encoder + reciprocal rank fusion
  reranker.py        cross-encoder reranking over policy text + applicability metadata
  corpus.py          loading and chunking
  synthesis.py       post-generation grounding check
  prompts.py         system prompt (contains no policy content, by design)
  order_ids.py       strict order-ID extraction ("Rs 5000" is not ORD-5000)
  tools/
    executor.py      deterministic policy gates around every tool call
    commerce_api.py  mock commerce backend
    schemas.py       tool definitions
  audit.py, session.py, llm.py, config.py, cli.py
data/                corpus.json (8 docs + metadata), mock_orders.json
evals/               retrieval_queries.yaml, scenarios.yaml, runners, results/
tests/
docs/                DESIGN.md, ASSUMPTIONS.md, architecture.svg, PLAN.md (original plan)
logs/                audit.jsonl (created at runtime, git-ignored)
```
