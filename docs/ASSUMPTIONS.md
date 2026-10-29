# Assumptions, Open Questions and Next Steps

## Assumptions

**Scope and tools**
- **Added a third tool, `raise_dispute(order_id, reason)`.** The brief specifies two tools, but the reference diagram lists `raise_dispute`, and example query 3 requires "proactively offer to initiate a dispute". Using `initiate_return` for a failed payment would be wrong: there is no item to return. It follows the same schema style and the same write-action gates.
- **Added `search_policy` and `escalate_to_human` as tools.** Retrieval is exposed as a tool so the model can combine it with order lookups in one turn. The human handoff is a tool so the model can trigger it, and code can also trigger it directly.
- **Return eligibility belongs to the backend.** The corpus has no return-window or return-eligibility policy. The mock API decides: only `DELIVERED` orders can be returned. The assistant never invents a return window. It says no policy covers it and lets the tool decide.
- **Dispute eligibility is "the stated window has elapsed".** For a failed payment, the window is 48 hours after the attempt (DOC-2). For a returned item, it is 7 business days after warehouse receipt (DOC-1), plus 3 for international orders (DOC-6). Where the documents give a range, I used the upper bound, so a dispute is never offered while the policy still says "wait".
- **"Business days" and "working days" both mean Monday to Friday, with no public holidays.** In production these come from a holiday calendar.

**Identity and data**
- **The customer is authenticated before the assistant runs.** The session carries `customer_id` (fixed to `CUST-001` here). The model never supplies it, so it cannot be talked into querying another account.
- **Orders owned by someone else look exactly like orders that don't exist.** Both return `ORDER_NOT_FOUND`, so the assistant can't be used to check whether an order ID is real.
- **Order IDs have the form `ORD-` plus 4 digits.** Extraction is deliberately strict. "Rs 5000" never becomes `ORD-5000`, and a model-proposed ID is rejected unless the customer typed it.
- **The order API returns no customer personal data,** only order facts. That is why tool results can go to the LLM and the audit log unredacted.

**Environment**
- **The simulated "now" is fixed at Sunday 27 Sep 2026, 10:00 UTC,** so timeline answers and tests are reproducible. The brief's example timestamps are in late September 2026.
- **The high-value threshold is Rs 25,000.** Returns and disputes above it go to a human. The brief gives no number, so this is a placeholder for a business decision.
- **Responses are in English, and the channel is chat.** Email would add threading and asynchronous confirmation, which is not designed here.

## What I would do differently with more time

1. **Replace the lexical grounding check with an entailment check.** Today the validator checks that every cited document was retrieved and that every timeline figure appears in a source. A coincidental number match passes, and non-numeric claims aren't checked. One eval run caught the model adding "keeps things faster for you", which nothing supports. A small NLI model, or an LLM judge on sampled traffic, would score each claim against its cited chunk.
2. **Build a real evaluation set from support logs.** The 17 labelled retrieval queries and the 21 scenarios were written by the same person who wrote the chunk metadata, so the 17/17 retrieval result measures fit, not generalisation. I'd sample and label a few hundred real queries, including Hinglish and typos.
3. **Answer pure FAQ questions in one LLM call.** About a third of turns need no order data. Running retrieval first and making a single synthesis call would cut those turns from 2 LLM calls to 1. LLM calls are 98% of latency.
4. **Stream responses.** The median turn takes 5.9s end to end, but streaming would get the first words on screen in about 2s.
5. **Make confirmation structured.** Confirmation currently requires the model to call the action tool in the turn it makes the offer. Weaker models often offer in plain text instead, and the customer then has to confirm twice. A UI confirm button bound to the registered action would remove that dependence on the model.
6. **Use a model-based injection classifier** alongside the regexes. The regexes are not the security boundary, but better detection means fewer locked conversations from false positives, and fewer misses.
7. **Persistent sessions and audit storage.** Sessions are in memory and the audit log is a local JSONL file, which is fine for one process. Production needs a session store and an append-only audit sink, such as a WORM bucket or a log pipeline.
8. **Hand chargeback cases to a human correctly.** If the customer has already raised a card chargeback with their bank, the platform dispute process may conflict with it. That needs a policy the corpus doesn't have.

## Questions I would ask at a real kickoff

**Policy and business rules**
- What decides return eligibility (return window, product categories, condition), and where is that defined? The corpus has nothing on it.
- What is the actual approval threshold for refunds and returns without a human? Does it vary by customer tier or payment method?
- For dispute timelines, does the clock start when the window elapses, or when the customer first contacts support?
- Should the assistant ever raise a dispute proactively, or always only when the customer asks?
- What is the escalation path's service level? The assistant currently promises a human follow-up with no timeframe, because none is documented.

**Data, compliance and vendors**
- Which LLM providers are approved for customer data, and in which regions? Is zero data retention required? This decides whether DeepSeek via OpenRouter is acceptable or whether provider routing must be pinned.
- What audit retention period applies, and who can read the audit log?
- Are Aadhaar, PAN and UPI handles in scope for redaction, or are there more identifiers specific to your payment stack?

**Integration**
- What does the real order API return? In particular, does it expose SLA dates and an `sla_breached` flag like the mock, or must the assistant derive them?
- Does the order API support a validate-only (dry-run) mode for returns and disputes? The confirmation design relies on checking eligibility before asking the customer to confirm.
- Is there an existing human-agent queue with an API, and what context does it accept?
- What channels must the assistant support at launch (app chat, web, email, WhatsApp)?

**Success criteria**
- What does success look like at launch: containment rate, CSAT, wrong-action rate, cost per conversation? Which of these is a hard gate?
- Is there a labelled set of past tickets we can evaluate against?
