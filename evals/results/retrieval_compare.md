# Retrieval comparison

17 in-scope queries, 3 out-of-scope.

| Configuration | Top-1 accuracy | MRR | Gold in top-3 | Trap group top-1 | Out-of-scope rejected |
|---|---|---|---|---|---|
| BM25 only | 13/17 | 0.853 | 15/17 | 5/6 | n/a (no calibrated score) |
| Bi-encoder only | 15/17 | 0.931 | 17/17 | 5/6 | n/a (no calibrated score) |
| Hybrid (RRF) | 14/17 | 0.902 | 17/17 | 5/6 | n/a (no calibrated score) |
| Hybrid + rerank | 16/17 | 0.971 | 17/17 | 5/6 | 3/3 |
| Hybrid + rerank + metadata | 17/17 | 1.000 | 17/17 | 6/6 | 3/3 |

## Per-query top-1 (✗ = wrong document ranked first)

| Query | Gold | BM25 only | Bi-encoder only | Hybrid (RRF) | Hybrid + rerank | Hybrid + rerank + metadata |
|---|---|---|---|---|---|---|
| my money got deducted and the order failed, when will I get it back | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 |
| I was charged but the order didn't go through, where is my refund? | DOC-2 | DOC-7 ✗ | DOC-1 ✗ | DOC-1 ✗ | DOC-1 ✗ | DOC-2 |
| amount debited but order not placed, refund status? | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 |
| payment failed but money deducted when will I get refund | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 |
| Money left my account but the app says the order failed. When is my refund coming? | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 |
| bank debited me but no order was created | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 | DOC-2 |
| How long will my refund take for order ORD-7701? | DOC-1 | DOC-6 ✗ | DOC-1 | DOC-1 | DOC-1 | DOC-1 |
| I returned the shoes last week, when will I get my refund? | DOC-1 | DOC-1 | DOC-1 | DOC-1 | DOC-1 | DOC-1 |
| the warehouse received my return, how many days until I get the money? | DOC-1 | DOC-1 | DOC-1 | DOC-1 | DOC-1 | DOC-1 |
| I returned an item from my international order, why is the refund taking longer? | DOC-6 | DOC-1 ✗ | DOC-6 | DOC-1 ✗ | DOC-6 | DOC-6 |
| how do I raise a dispute and how long does it take? | DOC-3 | DOC-6 ✗ | DOC-3 | DOC-1 ✗ | DOC-3 | DOC-3 |
| my dispute has been open for 2 weeks with no resolution, who can I escalate to? | DOC-8 | DOC-8 | DOC-3 ✗ | DOC-8 | DOC-8 | DOC-8 |
| I want to file a chargeback for my order | DOC-7 | DOC-7 | DOC-7 | DOC-7 | DOC-7 | DOC-7 |
| What's the maximum amount a single order can be? | DOC-5 | DOC-5 | DOC-5 | DOC-5 | DOC-5 | DOC-5 |
| is there a daily limit on how much I can spend? | DOC-5 | DOC-5 | DOC-5 | DOC-5 | DOC-5 | DOC-5 |
| Can you reset my account password for me right now? | DOC-4 | DOC-4 | DOC-4 | DOC-4 | DOC-4 | DOC-4 |
| I forgot my password | DOC-4 | DOC-4 | DOC-4 | DOC-4 | DOC-4 | DOC-4 |

## Top cross-encoder score for out-of-scope queries

- "what's the weather like in Mumbai": 0.0000 (threshold 0.01)
- "can you recommend a good laptop": 0.0000 (threshold 0.01)
- "how do I invest in mutual funds": 0.0004 (threshold 0.01)

## Status-aware filtering: "How long will it take to get my money back for my order?"

| Order status from tool | Hits passed to synthesis |
|---|---|
| (none) | DOC-1 (0.88), DOC-6 (0.62), DOC-2 (0.20) |
| PAYMENT_FAILED | DOC-2 (0.20), DOC-3 (0.04) |
| RETURN_RECEIVED | DOC-1 (0.88), DOC-6 (0.62), DOC-3 (0.04) |

## Latency (CPU, this machine, 8 chunks)

- retrieve: median 7 ms, max 8 ms
- rerank: median 72 ms, max 76 ms
